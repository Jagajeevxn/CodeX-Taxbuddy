import streamlit as st
import google.generativeai as genai
import json
import os
import time
from fpdf import FPDF

# 1. Set the page title and a friendly icon
st.set_page_config(page_title="AI TaxBuddy Pro (Final Clean Version) By CodeX", page_icon="🤖")

# --- INITIALIZE SESSION STATE ---
if 'extracted_data' not in st.session_state: st.session_state.extracted_data = None
if 'calculation_response' not in st.session_state: st.session_state.calculation_response = None
if 'final_calc_json' not in st.session_state: st.session_state.final_calc_json = None
if 'pdf_output_bytes' not in st.session_state: st.session_state.pdf_output_bytes = None
if 'user_80d' not in st.session_state: st.session_state.user_80d = 0
if "messages" not in st.session_state: st.session_state.messages = []
# *** MODEL NAME UPDATED HERE ***
if 'api_model' not in st.session_state: st.session_state.api_model = "gemini-2.5-flash"
# --- END SESSION STATE ---

# --- CONFIGURE THE GEMINI API ---
try:
    if "GOOGLE_API_KEY" not in st.secrets:
        raise Exception("API key not found.")

    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except Exception as e:
    st.error("FATAL ERROR: Your 'secrets.toml' file is missing or the API key is wrong.")
    st.error("Please go to Google AI Studio, get your API key, and put it in .streamlit/secrets.toml")
    st.stop()
# --- END NEW ---


# --- MASTER EXTRACTOR PROMPT (FIXED FORMAT) ---
extractor_prompt = (
    "You are \"TaxScan,\" an AI-powered data extraction specialist.\n"
    "Your sole objective is to analyze the provided financial document (image or PDF) and extract key financial information.\n"
    "Return the information in a strict JSON format.\n\n"
    "**Entities to Extract:**\n"
    "* `personal_info`: { `name`, `pan_number`, `assessment_year` }\n"
    "* `income_sources`: [ { `type` (e.g., 'Salary', 'Interest'), `amount` } ]\n"
    "* `deductions_claimed`: [ { `section` (e.g., '80C', '80D'), `amount` } ]\n"
    "* `taxes_paid`: { `tds` (Tax Deducted at Source), `advance_tax` }\n\n"
    "**Rules:**\n"
    "1.  If a value or section is not found, use `null`.\n"
    "2.  Do not infer or calculate. Only extract what is explicitly written.\n"
    "3.  Your response MUST be *only* the valid JSON.\n"
    "4.  Do not add ```json or any other markdown.\n"
    "5.  Start your response *immediately* with { and end it *immediately* with }."
)
# --- END EXTRACTOR PROMPT ---


# --- MASTER CALCULATOR PROMPT (MODIFIED FOR REGIME COMPARISON) ---
calculator_prompt = (
    "You are \"TaxLogic,\" an expert tax calculation engine.\n"
    "Your task is to calculate the user's final tax liability based on the provided JSON data under BOTH the Old and New tax regimes, and then recommend the best one.\n"
    "You MUST follow a strict Chain-of-Thought process. Show every step for both calculations.\n\n"
    "**Knowledge Base (Current Tax Rules):**\n"
    "1.  **Standard Deduction:** Flat ₹50,000. *Applicable to BOTH Old and New regimes* for salaried employees.\n"
    "2.  **Professional Tax:** Capped at ₹2,500. *Applicable to BOTH Old and New regimes*.\n"
    "3.  **Chapter VI-A Deductions (80C, 80D, etc.):** *Applicable ONLY to OLD REGIME*.\n"
    "    * Section 80C: Max ₹150,000.\n"
    "    * Section 80D: Max ₹25,000 (as provided).\n"
    "4.  **Rebate 87A:**\n"
    "    * **Old Regime:** If Taxable Income <= ₹5L, rebate is ₹12,500.\n"
    "    * **New Regime (Sec 87A):** If Taxable Income <= ₹7L, rebate is ₹25,000 (making 0 tax).\n"
    "5.  **Cess:** 4% Health and Education Cess on final tax (for both).\n\n"
    "**Tax Slabs (Old Regime):**\n"
    "* 0 - 2.5L: 0%\n"
    "* 2.5L - 5L: 5%\n"
    "* 5L - 10L: 20%\n"
    "* > 10L: 30%\n\n"
    "**Tax Slabs (New Regime - Sec 115BAC):**\n"
    "* 0 - 3L: 0%\n"
    "* 3L - 6L: 5%\n"
    "* 6L - 9L: 10%\n"
    "* 9L - 12L: 15%\n"
    "* 12L - 15L: 20%\n"
    "* > 15L: 30%\n\n"
    "**Instructions & Output Format:**\n"
    "1.  **Analyze Input:** Read the provided JSON.\n"
    "2.  **Calculate Gross Total Income:** Sum all `income_sources`.\n"
    "3.  **--- CALCULATION (OLD REGIME) ---**\n"
    "    a. Calculate Total Old Regime Deductions (Standard Ded. + 80C(max 1.5L) + 80D(max 25k) + etc.).\n"
    "    b. Calculate Old Regime Taxable Income: (Gross Total Income) - (Total Old Regime Deductions).\n"
    "    c. Apply Old Regime Slabs, Rebate 87A, and 4% Cess.\n"
    "    d. State the 'Final Tax (Old Regime)'.\n"
    "4.  **--- CALCULATION (NEW REGIME) ---**\n"
    "    a. Calculate Total New Regime Deductions (Standard Ded. only).\n"
    "    b. Calculate New Regime Taxable Income: (Gross Total Income) - (Total New Regime Deductions).\n"
    "    c. Apply New Regime Slabs, Rebate 87A, and 4% Cess.\n"
    "    d. State the 'Final Tax (New Regime)'.\n"
    "5.  **--- FINAL COMPARISON ---**\n"
    "    a. Compare 'Final Tax (Old Regime)' vs 'Final Tax (New Regime)'.\n"
    "    b. State which regime is recommended and the total tax saving.\n"
    "6.  **Calculate Taxes Paid:** Sum `tds` and `advance_tax`.\n"
    "7.  **Return TWO things:**\n"
    "    * Your entire Chain-of-Thought calculation (Steps 1-6) as clear text, using markdown headers for structure (e.g., #, ##, *) for better Streamlit display. Use 'Rs.' instead of '₹' in the text output.\n"
    "    * A final, single JSON object summarizing the result. The 'final_amount_due_under_recommendation' should be (Recommended Tax Liability) - (Taxes Paid).\n\n"
    "**Example Response Structure (Illustrative):**\n"
    "# Step-by-Step Calculation\n"
    "\n"
    "## 1. Gross Income\n"
    "...\n"
    "\n"
    "## 2. Old Regime Calculation\n"
    "...\n"
    "Final Tax (Old Regime): Rs.[Amount]\n"
    "\n"
    "## 3. New Regime Calculation\n"
    "...\n"
    "Final Tax (New Regime): Rs.[Amount]\n"
    "\n"
    "## 4. Comparison\n"
    "The [New/Old] Regime is recommended, saving you Rs.[Amount].\n"
    "\n"
    "{\n"
    "  \"gross_total_income\": ..., \n"
    "  \"total_taxes_paid\": ..., \n"
    "  \"old_regime_tax_liability\": ..., \n"
    "  \"new_regime_tax_liability\": ..., \n"
    "  \"recommended_regime\": \"Old\" or \"New\",\n"
    "  \"tax_saving_with_recommendation\": ..., \n"
    "  \"final_amount_due_under_recommendation\": ..., \n"
    "  \"status\": \"...\" # Based on final_amount_due_under_recommendation\n"
    "}"
)
# --- END MODIFIED CALCULATOR PROMPT ---


# --- GEMINI API FUNCTIONS ---
def get_gemini_response(uploaded_file, prompt):
    try:
        # Extractor uses Flash model
        # *** MODEL NAME UPDATED HERE ***
        model = genai.GenerativeModel("gemini-2.5-flash")
        file_data = {'mime_type': uploaded_file.type, 'data': uploaded_file.getvalue()}
        generation_config = genai.GenerationConfig(response_mime_type="application/json")
        response = model.generate_content([prompt, file_data], generation_config=generation_config)
        return json.loads(response.text)
    except Exception as e:
        st.error(f"AI Extractor failed: {e}")
        return None

def calculate_tax(data, prompt):
    try:
        # Calculator uses the model selected by the user in the sidebar
        model = genai.GenerativeModel(st.session_state.api_model)
        input_prompt = prompt + "\n\n**Input Data:**\n```json\n" + json.dumps(data, indent=2) + "\n```"
        response = model.generate_content(input_prompt)
        if response.parts:
            return response.text
        else:
            st.error("AI Calculator returned an empty response.")
            return None
    except Exception as e:
        # Check for Quota Exceeded (429) error and provide specific feedback
        if "429" in str(e) and "quota" in str(e).lower():
            st.error(f"AI Calculator failed: Quota Exceeded (429). Please switch the API Model in the sidebar to 'gemini-2.5-flash' to continue, or wait 24 hours.")
        else:
            st.error(f"AI Calculator failed: {e}")
        return None
# --- END GEMINI API FUNCTIONS ---


# --- PDF HELPER FUNCTIONS ---

def safe_str(val, default='N/A'):
    if val is None: return default
    return str(val)

def format_currency(val, default='0.00'):
    if val is None: return default
    try:
        return f"Rs. {float(val):,.2f}"
    except (ValueError, TypeError):
        return default

def create_pdf_report(extracted_data, calc_summary):
    pdf = FPDF()
    pdf.add_page() # Critical: must add a page before writing content!
    pdf.set_font("Arial", size=11)

    # Styles
    def add_title(title):
        pdf.set_font("Arial", 'B', 16)
        pdf.set_fill_color(200, 220, 255)
        pdf.cell(0, 10, title, 1, 1, 'C', 1)
        pdf.ln(5)

    def add_section(title):
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 8, title, 0, 1, 'L')
        pdf.set_font("Arial", size=11)

    def add_kv(key, value, bold_key=True):
        if bold_key: pdf.set_font("Arial", 'B', 11)
        pdf.cell(95, 7, txt=key)
        if bold_key: pdf.set_font("Arial", size=11)
        pdf.cell(0, 7, txt=value, ln=True)

    # --- PDF Content ---
    add_title("AI TaxBuddy - Dual Regime Tax Summary")

    # Part A: General Info
    add_section("1. General Information")
    info = extracted_data.get('personal_info', {})
    add_kv("Name:", safe_str(info.get('name')))
    add_kv("PAN:", safe_str(info.get('pan_number')))
    add_kv("Assessment Year:", safe_str(info.get('assessment_year', 'N/A')))
    pdf.ln(3)

    # Part B: Income & Deductions
    add_section("2. Income and Deductions")
    add_kv("Gross Total Income:", format_currency(calc_summary.get('gross_total_income')))
    add_kv("Total Taxes Paid (TDS/Advance Tax):", format_currency(calc_summary.get('total_taxes_paid')))

    pdf.ln(2)
    add_kv("Deductions Extracted/Added:", "", bold_key=False)
    for d in extracted_data.get('deductions_claimed', []):
        add_kv(f"  - Sec {safe_str(d.get('section'))}:", format_currency(d.get('amount')), bold_key=False)
    pdf.ln(5)

    # Part D: Tax Computation Comparison
    add_title("3. TAX REGIME COMPARISON")

    old_tax = calc_summary.get('old_regime_tax_liability', 0)
    new_tax = calc_summary.get('new_regime_tax_liability', 0)
    recommended = calc_summary.get('recommended_regime', 'N/A')
    saving = calc_summary.get('tax_saving_with_recommendation', 0)

    pdf.set_fill_color(240, 240, 240)
    pdf.set_draw_color(100, 100, 100)

    # Header for comparison table
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(63, 7, "Metric", 1, 0, 'C', 1)
    pdf.cell(63, 7, "Old Regime", 1, 0, 'C', 1)
    pdf.cell(64, 7, "New Regime", 1, 1, 'C', 1)
    pdf.set_font("Arial", size=11)

    # Tax Liability Row
    pdf.cell(63, 7, "Total Tax Liability (D1)", 1, 0)
    pdf.cell(63, 7, format_currency(old_tax), 1, 0, 'R')
    pdf.cell(64, 7, format_currency(new_tax), 1, 1, 'R')

    # Final Result
    pdf.ln(5)

    if recommended == "Old":
        pdf.set_text_color(0, 128, 0) # Green
        add_kv(f"RECOMMENDED REGIME: {recommended} (Best Choice)", f"Tax Savings: {format_currency(saving)}")
    elif recommended == "New":
        pdf.set_text_color(0, 128, 0) # Green
        add_kv(f"RECOMMENDED REGIME: {recommended} (Best Choice)", f"Tax Savings: {format_currency(saving)}")
    else:
        pdf.set_text_color(0, 0, 0)
        add_kv(f"RECOMMENDED REGIME:", f"Could not determine best option.", bold_key=True)

    pdf.set_text_color(0, 0, 0) # Reset color
    pdf.ln(5)

    # Final Amount Due (Based on Recommendation)
    add_section("4. Final Tax Position (Recommended Regime)")
    final_due = calc_summary.get('final_amount_due_under_recommendation', 0)
    status = calc_summary.get('status', 'Error')

    if status == "Tax Due":
        pdf.set_text_color(220, 50, 50) # Red
        add_kv("FINAL ACTION REQUIRED:", "TAX PAYMENT DUE")
        add_kv("Amount Payable:", format_currency(final_due))
    elif status == "Refund Due":
        pdf.set_text_color(0, 128, 0) # Green
        add_kv("FINAL ACTION REQUIRED:", "REFUND ELIGIBLE")
        add_kv("Refund Amount:", format_currency(abs(final_due)))
    else:
        pdf.set_text_color(0, 0, 0)
        add_kv("Final Status:", safe_str(status))
        add_kv("Final Amount:", format_currency(final_due))

    pdf.set_text_color(0, 0, 0) # Reset color

    # FIX: Encode the string output to bytes (latin-1) for Streamlit's download button
    return pdf.output(dest='S').encode('latin-1')

# --- END PDF FUNCTIONS ---


# --- NEW FUNCTION: Check relevance and get answer (For Chatbot - RADICAL FIX) ---
def check_relevance_and_get_answer(user_prompt, conversation_history, system_context):
    """
    RADICAL FIX: Creates a single, comprehensive prompt including all history and context
    to avoid role-management errors (400) and ensures context is always present.
    """
    try:
        # *** MODEL NAME UPDATED HERE ***
        relevance_model = genai.GenerativeModel("gemini-2.5-flash")

        # 1. Quick relevance check
        check_prompt = (
            "Analyze the following user question. Determine if it is related to personal finance, taxation, deductions, income, or tax filing. "
            "Respond ONLY with the word 'TAX' if it is relevant, or 'IRRELEVANT' if it is not."
            f"User Question: {user_prompt}"
        )
        relevance_response = relevance_model.generate_content(check_prompt)
        relevance_check = relevance_response.text.strip().upper()

        if "TAX" not in relevance_check:
            return "I am an AI Tax Advisor and can only answer questions related to your income, deductions, and tax planning. Please ask a tax-related question.", "irrelevant"

        # 2. If relevant, construct the full stateless prompt
        # *** MODEL NAME UPDATED HERE ***
        chat_model = genai.GenerativeModel("gemini-2.5-flash")

        # Build the conversation history string
        history_string = "--- CONVERSATION HISTORY ---\n"
        for msg in conversation_history:
            if msg["role"] != "system": # Ensure only user/assistant messages are included
                history_string += f"[{msg['role'].upper()}]: {msg['content']}\n"

        # Build the final, massive prompt (System Context + History + New Question)
        full_prompt = (
            f"SYSTEM CONTEXT: {system_context}\n\n"
            f"{history_string}\n"
            f"--- NEW USER QUESTION ---\n"
            f"[USER]: {user_prompt}\n\n"
            f"Please provide a helpful, personalized response based ONLY on the context and history provided above."
        )

        # The API call uses only the single prompt string
        response = chat_model.generate_content(full_prompt)
        return response.text, "relevant"

    except Exception as e:
        st.error(f"Error during AI Advisor generation: {e}")
        return "I am currently experiencing a technical issue. Please try your question again.", "error"
# --- END NEW FUNCTION ---


# --- UI LAYOUT ---
st.image("codex.png", width=200)
st.title("AI TaxBuddy Pro 🤖")
st.caption("Tax Regime Comparison and Personalized AI Advisor.")

# --- SIDEBAR (LIMIT FRAME) ---
st.sidebar.header("Step 1: Upload Documents")
uploaded_file = st.sidebar.file_uploader(
    "Upload your Form 16, etc. (PDF or JPG)",
    type=["pdf", "jpg", "png"]
)
st.sidebar.markdown("---")
st.sidebar.header("⚙️ API Settings (Quota Fix)")
st.session_state.api_model = st.sidebar.selectbox(
    "Select Model for Tax Calculation (Step 3):",
    # *** MODEL NAMES UPDATED HERE ***
    options=["gemini-2.5-flash", "gemini-2.5-pro"],
    index=0,
    key="model_selector",
    help="Using 'flash' to avoid the Quota Exceeded (429) error. 'pro' has strict free-tier limits (50/day)."
)
# *** MODEL NAME UPDATED HERE ***
if st.session_state.api_model == "gemini-2.5-pro":
    st.sidebar.warning("Selected: gemini-2.5-pro. Use with caution due to free-tier limits.")
else:
    st.sidebar.success("Selected: gemini-2.5-flash. Faster and higher limits.")
# --- END SIDEBAR ---


# --- PROCESSING LOGIC (Steps 1, 2, 3, 4) ---
if uploaded_file is not None:
    if st.session_state.extracted_data is None or \
       st.session_state.get('uploaded_filename') != uploaded_file.name:

        with st.spinner('Analyzing document... This may take a moment.'):
            # Clear all states on new upload
            st.session_state.extracted_data = None
            st.session_state.calculation_response = None
            st.session_state.final_calc_json = None
            st.session_state.pdf_output_bytes = None
            st.session_state.user_80d = 0
            st.session_state.messages = [] # Clear chat history

            # Extractor uses FLASH
            extracted_data = get_gemini_response(uploaded_file, extractor_prompt)

            if extracted_data:
                st.session_state.extracted_data = extracted_data
                st.session_state.uploaded_filename = uploaded_file.name
                st.sidebar.success(f"Successfully analyzed: {uploaded_file.name}")
            else:
                st.sidebar.error("Could not analyze the document.")
                st.session_state.uploaded_filename = None

if st.session_state.extracted_data:
    st.subheader("Step 2: Verify Extracted Data")

    # Display Extracted Data and Input for 80D in the main panel
    col1, col2 = st.columns([1, 2])

    with col1:
        st.info("Verification")
        st.session_state.user_80d = st.number_input(
            "Enter/Adjust 80D (Medical Insurance):",
            min_value=0,
            value=st.session_state.user_80d,
            key="user_80d_input_key"
        )

        if st.button("Calculate Tax Liability", type="primary", key="calc_button"):
            # Execute Calculation (Step 3)
            with st.spinner(f"Calculating... Comparing Old vs. New Regimes using {st.session_state.api_model}."):
                data_for_calc = st.session_state.extracted_data.copy()
                data_for_calc["deductions_claimed"] = data_for_calc.get("deductions_claimed", [])[:]

                # Add/Update 80D in the data sent to the AI
                user_80d_val = st.session_state.user_80d
                found_80d = False
                for d in data_for_calc["deductions_claimed"]:
                    if d.get("section") == "80D":
                        d["amount"] = user_80d_val
                        found_80d = True
                        break
                if not found_80d and user_80d_val > 0:
                    data_for_calc["deductions_claimed"].append({"section": "80D", "amount": user_80d_val})

                # Calculator uses the model selected in the sidebar
                response_text = calculate_tax(data_for_calc, calculator_prompt)
                st.session_state.calculation_response = response_text
                st.session_state.final_calc_json = None
                st.session_state.pdf_output_bytes = None

    with col2:
        st.json(st.session_state.extracted_data)

    st.markdown("---")


    # --- Display Calculation Results (Step 4 & 5) ---
    if st.session_state.calculation_response:
        st.subheader("Step 3: Tax Calculation & Comparison")

        # 4a. Attempt to parse and store the final JSON summary
        try:
            json_block_start = st.session_state.calculation_response.rfind('{')
            json_block_end = st.session_state.calculation_response.rfind('}') + 1
            if json_block_start != -1 and json_block_end > json_block_start:
                final_json_str = st.session_state.calculation_response[json_block_start:json_block_end]
                final_json_obj = json.loads(final_json_str)
                st.session_state.final_calc_json = final_json_obj
            else:
                 st.error("Could not find the JSON block in the AI's calculation response.")
                 st.session_state.final_calc_json = None
        except Exception as e:
            st.error(f"Could not parse final JSON summary: {e}")
            st.session_state.final_calc_json = None


        # 4b. Display Results
        if st.session_state.final_calc_json:
            st.success("Calculation complete! See the recommendation below.")

            # Use two columns for better comparison view
            rec_regime = st.session_state.final_calc_json.get("recommended_regime", "N/A")
            tax_saving = st.session_state.final_calc_json.get("tax_saving_with_recommendation", 0)
            old_tax = st.session_state.final_calc_json.get("old_regime_tax_liability", 0)
            new_tax = st.session_state.final_calc_json.get("new_regime_tax_liability", 0)

            rec_col, old_col, new_col = st.columns(3)

            rec_col.metric(
                label="**Recommended Regime**",
                value=rec_regime,
                delta=f"Saves {format_currency(tax_saving)}",
                delta_color="normal"
            )
            old_col.metric(
                label="Old Regime Tax",
                value=format_currency(old_tax)
            )
            new_col.metric(
                label="New Regime Tax",
                value=format_currency(new_tax)
            )

            st.markdown("---")

            # --- FINAL DEDUCTION DISPLAY FORMATTING ---
            final_due = st.session_state.final_calc_json.get('final_amount_due_under_recommendation', 0)
            status = st.session_state.final_calc_json.get('status', 'Error')

            st.subheader("Final Recommended Tax Position")
            if status == "Refund Due" or final_due < 0:
                st.success(f"🎉 **TAX REFUND ELIGIBLE!** 🎉")
                st.markdown(f"**Refund Amount:** {format_currency(abs(final_due))}")
            elif status == "Tax Due" or final_due > 0:
                st.error(f"⚠️ **TAX PAYMENT DUE!** ⚠️")
                st.markdown(f"**Amount Payable:** {format_currency(final_due)}")
            else:
                st.info(f"✅ **NO TAX DUE/REFUND**")
                st.markdown(f"**Final Amount:** {format_currency(0)}")

            st.markdown("---")
            st.markdown("**AI Chain-of-Thought Calculation Details:**")
            st.markdown(st.session_state.calculation_response)


            # 5. Generate and Download PDF Report
            st.subheader("Step 4: Download Report")

            # --- NEW: Use columns for download buttons ---
            pdf_col, json_col = st.columns(2)

            with pdf_col:
                if st.button("Generate ITR Summary PDF", type="secondary", key="gen_pdf_button"):
                    with st.spinner("Generating PDF report..."):
                        pdf_bytes = create_pdf_report(
                            st.session_state.extracted_data,
                            st.session_state.final_calc_json
                        )
                        st.session_state.pdf_output_bytes = pdf_bytes

                if st.session_state.pdf_output_bytes:
                    st.download_button(
                        label="Download ITR Summary PDF",
                        data=st.session_state.pdf_output_bytes,
                        file_name="TaxBuddy_Regime_Comparison.pdf",
                        mime="application/pdf",
                        key="download_pdf_button"
                    )

            with json_col:
                # --- NEW: Add a download button for the calculation JSON ---
                if st.session_state.final_calc_json:
                    # We must convert the dict to a string using json.dumps
                    json_string = json.dumps(st.session_state.final_calc_json, indent=2)

                    st.download_button(
                        label="Download Calculation JSON",
                        data=json_string,
                        file_name="TaxBuddy_Calculation.json",
                        mime="application/json",
                        key="download_json_button"
                    )
                else:
                    st.button("Download Calculation JSON", disabled=True)

            st.markdown("---")

            # --- AI Tax Advisor Feature (Step 5) ---
            st.subheader("Step 5: Ask Your AI Tax Advisor 🤖")
            st.info("Ask me things like: 'How can I maximize my 80C deduction?' or 'Why is the New Regime better for me?'")

            # Define the system prompt content based on calculation results
            system_prompt_content = (
                "You are a helpful, non-filing AI Tax Advisor. Use the following user tax context to give personalized, actionable advice on tax planning, savings, and explaining the comparison between the Old and New tax regimes. "
                "The extracted data is:\n"
                f"{json.dumps(st.session_state.extracted_data, indent=2)}\n"
                "The calculation result is:\n"
                f"{json.dumps(st.session_state.final_calc_json, indent=2)}"
            )

            # Initialize chat history
            if not st.session_state.messages or (len(st.session_state.messages) < 2 and st.session_state.messages[-1]["role"] != "assistant"):
                st.session_state.messages = [
                    {"role": "assistant", "content": "Hello! I've analyzed your tax profile and compared the Old and New regimes. How can I help you plan or understand your tax situation better?"}
                ]

            # Display chat messages from history
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            # Accept user input
            if prompt := st.chat_input("Ask about your tax..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                # --- SHOW SPINNER WHILE THINKING ---
                with st.spinner("AI Tax Advisor is thinking..."):
                    # Call the new checker/generator function
                    response_text, status = check_relevance_and_get_answer(
                        prompt,
                        st.session_state.messages,
                        system_prompt_content
                    )
                # --- END SPINNER ---

                # Display and update history based on the result
                with st.chat_message("assistant"):
                    st.markdown(response_text)

                # Only store the response if it was relevant or a non-error response
                if status != "error":
                    st.session_state.messages.append({"role": "assistant", "content": response_text})


# --- Show initial message only if no file has been uploaded yet ---
elif not uploaded_file and 'extracted_data' not in st.session_state or st.session_state.extracted_data is None:
     st.info("Please upload a document to get started. You can upload in the sidebar on the left.")