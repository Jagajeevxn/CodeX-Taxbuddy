import streamlit as st
import google.generativeai as genai
import json
import os
import time
from fpdf import FPDF
import datetime
import pandas as pd

# --- NEW IMPORTS ---
import plotly.graph_objects as go
from streamlit_calendar import calendar
import plotly.express as px

# --- IMPORTS FOR AUTH & DB ---
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import db_utils
# --- END NEW IMPORTS ---


# 1. Set the page title
st.set_page_config(page_title="AI TaxBuddy Pro (Final Clean Version) By CodeX", page_icon="🤖", layout="wide")

# --- INITIALIZE SESSION STATE ---
if 'extracted_data' not in st.session_state: st.session_state.extracted_data = None
if 'calculation_response' not in st.session_state: st.session_state.calculation_response = None
if 'final_calc_json' not in st.session_state: st.session_state.final_calc_json = None
if 'pdf_output_bytes' not in st.session_state: st.session_state.pdf_output_bytes = None
if 'user_80d' not in st.session_state: st.session_state.user_80d = 0.0 # Use float
if "messages" not in st.session_state: st.session_state.messages = []
if 'api_model' not in st.session_state: st.session_state.api_model = "gemini-2.5-flash"
# --- END SESSION STATE ---

# --- DATABASE INITIALIZATION ---
db_utils.create_tables()
# --- END DB INIT ---


# --- AUTHENTICATOR SETUP ---
try:
    with open('.streamlit/config.yaml') as file:
        config = yaml.load(file, Loader=SafeLoader)
except FileNotFoundError:
    st.error("FATAL ERROR: '.streamlit/config.yaml' file not found.")
    st.stop()
except Exception as e:
    st.error(f"Error loading config.yaml: {e}")
    st.stop()


authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

# Render the login widget
authenticator.login(location='main')
# --- END AUTHENTICATOR SETUP ---


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


# --- MASTER CALCULATOR PROMPT (UPDATED FOR PROFESSIONAL TAX & ROBUST PARSING) ---
calculator_prompt = (
    "You are \"TaxLogic,\" an expert tax calculation engine.\n"
    "Your task is to calculate the user's final tax liability based on the provided JSON data under BOTH the Old and New tax regimes, and then recommend the best one.\n"
    "You MUST follow a strict Chain-of-Thought process. Show every step for both calculations.\n\n"
    "**Knowledge Base (Current Tax Rules):**\n"
    "1.  **Standard Deduction:** Flat ₹50,000. *Applicable to BOTH Old and New regimes* for salaried employees.\n"
    "2.  **Professional Tax:** This is provided in the JSON as `professional_tax`. It is capped at ₹2,500. *Applicable to BOTH Old and New regimes*.\n"
    "3.  **Chapter VI-A Deductions (80C, 80D, etc.):** *Applicable ONLY to OLD REGIME*.\n"
    "    * Section 80C: Max ₹150,000.\n"
    "    * Section 80D: Use the value from the JSON.\n"
    "4.  **Rebate 87A:**\n"
    "    * **Old Regime:** If Taxable Income <= ₹5L, rebate is ₹12,500.\n"
    "    * **New Regime (Sec 87A):** If Taxable Income <= ₹7L, rebate is ₹25,000 (making 0 tax).\n"
    "5.  **Cess:** 4% Health and Education Cess on final tax (for both).\n\n"
    "**Tax Slabs (Old Regime):**\n"
    "* 0 - 2.5L: 0%\n* 2.5L - 5L: 5%\n* 5L - 10L: 20%\n* > 10L: 30%\n\n"
    "**Tax Slabs (New Regime - Sec 115BAC):**\n"
    "* 0 - 3L: 0%\n* 3L - 6L: 5%\n* 6L - 9L: 10%\n* 9L - 12L: 15%\n* 12L - 15L: 20%\n* > 15L: 30%\n\n"
    "**Instructions & Output Format:**\n"
    "1.  **Analyze Input:** Read the provided JSON. Note the `professional_tax` amount.\n"
    "2.  **Calculate Gross Total Income:** Sum all `income_sources`.\n"
    "3.  **--- CALCULATION (OLD REGIME) ---**\n"
    "    a. Calculate Total Old Regime Deductions (Standard Ded. + Professional Tax (max 2.5k) + 80C(max 1.5L) + 80D + etc.).\n"
    "    b. Calculate Old Regime Taxable Income: (Gross Total Income) - (Total Old Regime Deductions).\n"
    "    c. Apply Old Regime Slabs, Rebate 87A, and 4% Cess.\n"
    "    d. State the 'Final Tax (Old Regime)'.\n"
    "4.  **--- CALCULATION (NEW REGIME) ---**\n"
    "    a. Calculate Total New Regime Deductions (Standard Ded. + Professional Tax (max 2.5k) only).\n"
    "    b. Calculate New Regime Taxable Income: (Gross Total Income) - (Total New Regime Deductions).\n"
    "    c. Apply New Regime Slabs, Rebate 87A, and 4% Cess.\n"
    "    d. State the 'Final Tax (New Regime)'.\n"
    "5.  **--- FINAL COMPARISON ---**\n"
    "    a. Compare 'Final Tax (Old Regime)' vs 'Final Tax (New Regime)'.\n"
    "    b. State which regime is recommended and the total tax saving.\n"
    "6.  **Calculate Taxes Paid:** Sum `tds` and `advance_tax`.\n"
    "7.  **Return TWO things:**\n"
    "    * Your entire Chain-of-Thought calculation (Steps 1-6) as clear text, using markdown headers.\n"
    "    * A final, single JSON object summarizing the result. You MUST wrap this JSON object in unique tags: `<JSON_OUTPUT>` and `</JSON_OUTPUT>`.\n\n"
    "**Example Response Structure (Illustrative):**\n"
    "# Step-by-Step Calculation\n"
    "...\n"
    "Final Tax (New Regime): Rs.[Amount]\n"
    "\n"
    "<JSON_OUTPUT>\n"
    "{\n"
    "  \"gross_total_income\": ..., \n"
    "  \"total_taxes_paid\": ..., \n"
    "  \"old_regime_tax_liability\": ..., \n"
    "  \"new_regime_tax_liability\": ..., \n"
    "  \"recommended_regime\": \"Old\" or \"New\",\n"
    "  \"tax_saving_with_recommendation\": ..., \n"
    "  \"final_amount_due_under_recommendation\": ..., \n"
    "  \"status\": \"...\" \n"
    "}\n"
    "</JSON_OUTPUT>"
)
# --- END MODIFIED CALCULATOR PROMPT ---

# --- NEW: AI INVESTMENT PLANNER PROMPT ---
investment_prompt = (
    "You are \"FinVest AI,\" an expert financial advisor.\n"
    "Based on the user's provided tax calculation summary, analyze their financial position (Gross Income, Tax Liability, and Savings) and provide personalized, actionable investment suggestions.\n"
    "The user's goal is to **both save tax and grow wealth**.\n\n"
    "**User's Data:**\n"
    "{user_data_json}\n\n"
    "**Instructions:**\n"
    "1.  Acknowledge their key financial figures (Income, Recommended Tax).\n"
    "2.  Suggest **Tax-Saving Investments** (e.g., ELSS, PPF, NPS) that they could use to maximize their 80C limit (if they chose the Old Regime or might in the future).\n"
    "3.  Suggest **Wealth-Growth Investments** based on their apparent income bracket (e.g., Mutual Funds (Index, Flexi-cap), Stocks, Bonds).\n"
    "4.  Provide a **sample diversified portfolio** (e.g., 60% Equity, 30% Debt, 10% Gold).\n"
    "5.  Conclude with a clear disclaimer that you are an AI and this is not financial advice, and they should consult a human expert."
)
# --- END INVESTMENT PROMPT ---

# --- PROFESSIONAL TAX DATA ---
professional_tax_by_state = {
    "Andhra Pradesh": 2400, "Assam": 2500, "Bihar": 2500, "Goa": 2500,
    "Gujarat": 2400, "Jharkhand": 2500, "Karnataka": 2400, "Kerala": 2500,
    "Madhya Pradesh": 2500, "Maharashtra": 2500, "Manipur": 2400, "Meghalaya": 2500,
    "Mizoram": 2500, "Nagaland": 2500, "Odisha": 2500, "Puducherry": 2500,
    "Punjab": 2400, "Sikkim": 2500, "Tamil Nadu": 2500, "Telangana": 2400,
    "Tripura": 2500, "West Bengal": 2400,
    "Other (Not Listed)": 0
}
# --- END P-TAX DATA ---


# --- GEMINI API FUNCTIONS ---
def get_gemini_response(uploaded_file, prompt):
    try:
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
        model = genai.GenerativeModel(st.session_state.api_model)
        input_prompt = prompt + "\n\n**Input Data:**\n```json\n" + json.dumps(data, indent=2) + "\n```"
        response = model.generate_content(input_prompt)
        if response.parts:
            return response.text
        else:
            st.error("AI Calculator returned an empty response.")
            return None
    except Exception as e:
        if "429" in str(e) and "quota" in str(e).lower():
            st.error(f"AI Calculator failed: Quota Exceeded (429).")
        else:
            st.error(f"AI Calculator failed: {e}")
        return None

# --- NEW: GEMINI FUNCTION FOR INVESTMENT ADVICE ---
def get_investment_advice(user_data, prompt_template):
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        input_prompt = prompt_template.format(user_data_json=json.dumps(user_data, indent=2))
        response = model.generate_content(input_prompt)
        return response.text
    except Exception as e:
        st.error(f"AI Advisor failed: {e}")
        return "Could not generate advice at this time."
# --- END GEMINI FUNCTIONS ---


# --- PDF HELPER FUNCTIONS ---
def safe_str(val, default='N/A'):
    if val is None: return default
    return str(val)

def format_currency(val, default='Rs. 0.00'):
    if val is None: return default
    try:
        return f"Rs. {float(val):,.2f}"
    except (ValueError, TypeError):
        return default

def create_pdf_report(extracted_data, calc_summary):
    pdf = FPDF()
    pdf.add_page()
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
    info = extracted_data.get('personal_info', {})
    add_section("1. General Information")
    add_kv("Name:", safe_str(info.get('name')))
    add_kv("PAN:", safe_str(info.get('pan_number')))
    add_kv("Assessment Year:", safe_str(info.get('assessment_year', 'N/A')))
    pdf.ln(3)
    add_section("2. Income and Deductions")
    add_kv("Gross Total Income:", format_currency(calc_summary.get('gross_total_income')))
    add_kv("Total Taxes Paid (TDS/Advance Tax):", format_currency(calc_summary.get('total_taxes_paid')))
    pdf.ln(2)
    add_kv("Deductions Extracted/Added:", "", bold_key=False)

    all_deductions = calc_summary.get("deductions_used_for_old_regime", [])
    if not all_deductions: # Fallback
        all_deductions = extracted_data.get('deductions_claimed', [])

    for d in all_deductions:
        add_kv(f"  - Sec {safe_str(d.get('section'))}:", format_currency(d.get('amount')), bold_key=False)
    pdf.ln(5)

    add_title("3. TAX REGIME COMPARISON")
    old_tax = calc_summary.get('old_regime_tax_liability', 0)
    new_tax = calc_summary.get('new_regime_tax_liability', 0)
    recommended = calc_summary.get('recommended_regime', 'N/A')
    saving = calc_summary.get('tax_saving_with_recommendation', 0)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_draw_color(100, 100, 100)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(63, 7, "Metric", 1, 0, 'C', 1)
    pdf.cell(63, 7, "Old Regime", 1, 0, 'C', 1)
    pdf.cell(64, 7, "New Regime", 1, 1, 'C', 1)
    pdf.set_font("Arial", size=11)
    pdf.cell(63, 7, "Total Tax Liability", 1, 0)
    pdf.cell(63, 7, format_currency(old_tax), 1, 0, 'R')
    pdf.cell(64, 7, format_currency(new_tax), 1, 1, 'R')
    pdf.ln(5)
    if recommended == "Old":
        pdf.set_text_color(0, 128, 0); add_kv(f"RECOMMENDED REGIME: {recommended} (Best Choice)", f"Tax Savings: {format_currency(saving)}")
    elif recommended == "New":
        pdf.set_text_color(0, 128, 0); add_kv(f"RECOMMENDED REGIME: {recommended} (Best Choice)", f"Tax Savings: {format_currency(saving)}")
    else:
        pdf.set_text_color(0, 0, 0); add_kv(f"RECOMMENDED REGIME:", f"Could not determine best option.", bold_key=True)
    pdf.set_text_color(0, 0, 0); pdf.ln(5)
    add_section("4. Final Tax Position (Recommended Regime)")
    final_due = calc_summary.get('final_amount_due_under_recommendation', 0)
    status = calc_summary.get('status', 'Error')
    if status == "Tax Due":
        pdf.set_text_color(220, 50, 50); add_kv("FINAL ACTION REQUIRED:", "TAX PAYMENT DUE"); add_kv("Amount Payable:", format_currency(final_due))
    elif status == "Refund Due":
        pdf.set_text_color(0, 128, 0); add_kv("FINAL ACTION REQUIRED:", "REFUND ELIGIBLE"); add_kv("Refund Amount:", format_currency(abs(final_due)))
    else:
        pdf.set_text_color(0, 0, 0); add_kv("Final Status:", safe_str(status)); add_kv("Final Amount:", format_currency(final_due))
    pdf.set_text_color(0, 0, 0)
    return pdf.output(dest='S').encode('latin-1')
# --- END PDF FUNCTIONS ---


# --- CHATBOT FUNCTION ---
def check_relevance_and_get_answer(user_prompt, conversation_history, system_context):
    try:
        relevance_model = genai.GenerativeModel("gemini-2.5-flash")
        check_prompt = (
            "Analyze the following user question. Determine if it is related to personal finance, taxation, deductions, income, or tax filing. "
            "Respond ONLY with the word 'TAX' if it is relevant, or 'IRRELEVANT' if it is not."
            f"User Question: {user_prompt}"
        )
        relevance_response = relevance_model.generate_content(check_prompt)
        relevance_check = relevance_response.text.strip().upper()

        if "TAX" not in relevance_check:
            return "I am an AI Tax Advisor and can only answer questions related to your income, deductions, and tax planning. Please ask a tax-related question.", "irrelevant"

        chat_model = genai.GenerativeModel("gemini-2.5-flash")
        history_string = "--- CONVERSATION HISTORY ---\n"
        for msg in conversation_history:
            if msg["role"] != "system":
                history_string += f"[{msg['role'].upper()}]: {msg['content']}\n"
        full_prompt = (
            f"SYSTEM CONTEXT: {system_context}\n\n"
            f"{history_string}\n"
            f"--- NEW USER QUESTION ---\n"
            f"[USER]: {user_prompt}\n\n"
            f"Please provide a helpful, personalized response based ONLY on the context and history provided above."
        )
        response = chat_model.generate_content(full_prompt)
        return response.text, "relevant"

    except Exception as e:
        st.error(f"Error during AI Advisor generation: {e}")
        return "I am currently experiencing a technical issue. Please try your question again.", "error"
# --- END CHATBOT FUNCTION ---


# --- NEW: HRA HELPER FUNCTION ---
def calculate_hra_exemption(basic_salary, da, hra_received, rent_paid, city_type):
    """Calculates HRA exemption."""
    salary_for_hra = basic_salary + da
    rent_paid_over_salary = rent_paid - (0.10 * salary_for_hra)

    if city_type == "Metro":
        city_allowance = 0.50 * salary_for_hra
    else:
        city_allowance = 0.40 * salary_for_hra

    exemption = max(0, min(hra_received, rent_paid_over_salary, city_allowance))
    return exemption
# --- END HRA FUNCTION ---


# --- NEW: PLOTLY HELPER FUNCTION ---
def create_plotly_charts(calc_json, income_sources):
    """Generates Plotly charts for regime comparison and income breakdown."""

    # 1. Regime Comparison Chart
    regime_data = {
        'Regime': ['Old Regime', 'New Regime'],
        'Tax Liability': [
            calc_json.get('old_regime_tax_liability', 0),
            calc_json.get('new_regime_tax_liability', 0)
        ]
    }
    df_regime = pd.DataFrame(regime_data)

    fig_regime = px.bar(df_regime, x='Regime', y='Tax Liability',
                        title="Tax Liability Comparison",
                        color='Regime', text='Tax Liability',
                        color_discrete_map={'Old Regime': '#0068C9', 'New Regime': '#83C9FF'})
    fig_regime.update_traces(texttemplate='Rs. %{text:,.0f}', textposition='outside')
    st.plotly_chart(fig_regime, use_container_width=True)

    # 2. Income Breakdown Chart
    if income_sources:
        df_income = pd.DataFrame(income_sources)
        fig_income = px.pie(df_income, values='amount', names='type',
                            title="Income Sources Breakdown",
                            hole=0.3)
        fig_income.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig_income, use_container_width=True)

# --- END PLOTLY FUNCTION ---


# --- APPLICATION LOGIC (GATED BY LOGIN) ---
name = st.session_state.get('name')
authentication_status = st.session_state.get('authentication_status')
username = st.session_state.get('username')

if authentication_status:

    # --- CONFIGURE THE GEMINI API ---
    try:
        if "GOOGLE_API_KEY" not in st.secrets:
            raise Exception("API key not found.")
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    except Exception as e:
        st.error("FATAL ERROR: Your 'secrets.toml' file is missing or the API key is wrong.")
        st.stop()
    # --- END API CONFIG ---

    # --- AUTHENTICATED APP UI ---

    # --- SIDEBAR ---
    with st.sidebar:
        st.subheader(f"Welcome {name}!")
        authenticator.logout('Logout', 'sidebar', key='logout_button')

        st.sidebar.markdown("---")
        st.sidebar.header("⚙️ Global Settings")

        selected_state = st.sidebar.selectbox(
            "Select Your State (for Professional Tax):",
            options=list(professional_tax_by_state.keys())
        )
        prof_tax_amount = professional_tax_by_state.get(selected_state, 0)
        st.sidebar.info(f"Professional Tax set to: **Rs. {prof_tax_amount:,.0f}**")

        st.sidebar.markdown("---")
        st.session_state.api_model = st.sidebar.selectbox(
            "Select Model for Tax Calculation:",
            options=["gemini-2.5-flash", "gemini-2.5-pro"],
            index=0, key="model_selector"
        )
    # --- END SIDEBAR ---

    st.image("codex.png", width=200)
    st.title("AI TaxBuddy Pro 🤖")
    st.caption("Your complete tax planning and calculation dashboard.")

    # --- NEW: TABBED INTERFACE ---
    tab_dashboard, tab_deductions, tab_hra, tab_cap_gains, tab_invest, tab_calendar, tab_profile, tab_saved = st.tabs([
        "📊 Dashboard", "💸 Deduction Tracker", "🏠 HRA Calculator", "📈 Capital Gains",
        "💡 Investment Planner", "🗓️ Tax Calendar", "👤 My Profile", "🗂️ Saved Reports"
    ])

    # --- TAB 1: DASHBOARD (Main Calculator) ---
    with tab_dashboard:
        st.header("Tax Regime Comparison Dashboard")

        uploaded_file = st.file_uploader(
            "Upload your Form 16, etc. (PDF or JPG) to start",
            type=["pdf", "jpg", "png"],
            key="main_uploader"
        )

        if uploaded_file:
            if st.session_state.extracted_data is None or \
               st.session_state.get('uploaded_filename') != uploaded_file.name:
                with st.spinner('Analyzing document...'):
                    st.session_state.extracted_data = get_gemini_response(uploaded_file, extractor_prompt)
                    st.session_state.uploaded_filename = uploaded_file.name
                    st.session_state.calculation_response = None
                    st.session_state.final_calc_json = None
                    st.session_state.messages = [] # Reset chat on new upload

        if st.session_state.extracted_data:
            st.subheader("Step 1: Verify Extracted Data")
            col1, col2 = st.columns([1, 2])
            with col1:
                st.info("Verification")
                deduction_summary = db_utils.get_deductions_summary(username)
                st.session_state.user_80d = 0.0 # Use float
                for item in deduction_summary:
                    if item['section'] == '80D':
                        st.session_state.user_80d = float(item['total_amount']) # Cast to float

                st.session_state.user_80d = st.number_input(
                    "Adjust 80D (Medical Insurance):",
                    min_value=0.0, # Changed to float
                    value=float(st.session_state.user_80d), # Changed to float
                    key="user_80d_input_key"
                )

                st.caption(f"Tip: Add detailed deductions in the 'Deduction Tracker' tab.")

                if st.button("Calculate Tax Liability", type="primary", key="calc_button"):
                    with st.spinner(f"Calculating... using {st.session_state.api_model}."):
                        data_for_calc = st.session_state.extracted_data.copy()

                        all_deductions_list = data_for_calc.get("deductions_claimed", [])[:]

                        # Add/Update 80D
                        found_80d = False
                        for d in all_deductions_list:
                            if d.get("section") == "80D":
                                d["amount"] = st.session_state.user_80d; found_80d = True; break
                        if not found_80d and st.session_state.user_80d > 0:
                            all_deductions_list.append({"section": "80D", "amount": st.session_state.user_80d})

                        # Add Professional Tax
                        data_for_calc["professional_tax"] = prof_tax_amount

                        # Get other deductions from DB
                        for item in deduction_summary:
                            if item['section'] != '80D':
                                found_sec = False
                                for d_item in all_deductions_list:
                                    if d_item.get("section") == item['section']:
                                        # Aggregate amounts if section already exists
                                        d_item["amount"] = d_item.get("amount", 0) + item['total_amount']
                                        found_sec = True
                                        break
                                if not found_sec:
                                    all_deductions_list.append({"section": item['section'], "amount": item['total_amount']})

                        data_for_calc["deductions_claimed"] = all_deductions_list
                        st.session_state.deductions_for_pdf = all_deductions_list

                        response_text = calculate_tax(data_for_calc, calculator_prompt)
                        st.session_state.calculation_response = response_text
                        st.session_state.final_calc_json = None

            with col2:
                st.json(st.session_state.extracted_data)
            st.markdown("---")

        if st.session_state.calculation_response:
            st.subheader("Step 2: Tax Calculation & Comparison")

            try:
                response_text = st.session_state.calculation_response
                json_block_start = response_text.find('<JSON_OUTPUT>')
                json_block_end = response_text.find('</JSON_OUTPUT>')

                if json_block_start != -1 and json_block_end != -1 and json_block_end > json_block_start:
                    json_str_start = json_block_start + len('<JSON_OUTPUT>')
                    final_json_str = response_text[json_str_start:json_block_end].strip()
                    final_json_obj = json.loads(final_json_str)
                    final_json_obj["assessment_year"] = st.session_state.extracted_data.get('personal_info', {}).get('assessment_year', 'N/A')
                    final_json_obj["deductions_used_for_old_regime"] = st.session_state.get('deductions_for_pdf', [])
                    st.session_state.final_calc_json = final_json_obj
                else:
                     st.error("Could not find the JSON block in the AI's calculation response.")
                     with st.expander("AI Response (Debug View)"):
                         st.text(st.session_state.calculation_response[:1000] + "...")
            except Exception as e:
                st.error(f"Could not parse final JSON summary: {e}")
                with st.expander("AI Response (Debug View)"):
                     st.text(st.session_state.calculation_response[:1000] + "...")

            if st.session_state.final_calc_json:
                st.success("Calculation complete! See the recommendation below.")

                create_plotly_charts(st.session_state.final_calc_json, st.session_state.extracted_data.get('income_sources'))

                st.markdown("---")
                st.subheader("Final Recommended Tax Position")

                final_due = st.session_state.final_calc_json.get('final_amount_due_under_recommendation', 0)
                status = st.session_state.final_calc_json.get('status', 'Error')
                if status == "Refund Due" or final_due < 0:
                    st.success(f"🎉 **TAX REFUND ELIGIBLE!** | Refund Amount: **{format_currency(abs(final_due))}**")
                elif status == "Tax Due" or final_due > 0:
                    st.error(f"⚠️ **TAX PAYMENT DUE!** | Amount Payable: **{format_currency(final_due)}**")
                else:
                    st.info(f"✅ **NO TAX DUE/REFUND**")

                st.markdown("---")
                st.subheader("Step 3: Save & Download")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("💾 Save Calculation to Profile", key="save_calc"):
                        try:
                            db_utils.save_calculation(username, st.session_state.final_calc_json)
                            st.success("Calculation saved! Find it in 'Saved Reports'.")
                        except Exception as e:
                            st.error(f"Failed to save calculation: {e}")
                with col2:
                    pdf_bytes = create_pdf_report(st.session_state.extracted_data, st.session_state.final_calc_json)
                    st.download_button(
                        label="Download PDF Report", data=pdf_bytes,
                        file_name="TaxBuddy_Report.pdf", mime="application/pdf"
                    )
                with col3:
                    json_string = json.dumps(st.session_state.final_calc_json, indent=2)
                    st.download_button(
                        label="Download Calculation JSON", data=json_string,
                        file_name="TaxBuddy_Calculation.json", mime="application/json"
                    )

                st.markdown("---")

                # --- CHATBOT FIX (Layout) ---
                st.subheader("Step 4: Ask Your AI Tax Advisor 🤖")
                system_prompt_content = (f"Context:\n{json.dumps(st.session_state.extracted_data)}\n{json.dumps(st.session_state.final_calc_json)}")

                if "messages" not in st.session_state or not st.session_state.messages:
                    st.session_state.messages = [{"role": "assistant", "content": "Hello! I've analyzed your tax profile. How can I help?"}]

                # Create a container for the chat history
                chat_container = st.container(height=400, border=True)

                # Display all chat messages from history inside the container
                with chat_container:
                    for message in st.session_state.messages:
                        with st.chat_message(message["role"]):
                            st.markdown(message["content"])

                # Accept user input
                if prompt := st.chat_input("Ask about your tax..."):
                    st.session_state.messages.append({"role": "user", "content": prompt})

                    with chat_container:
                        with st.chat_message("user"):
                            st.markdown(prompt)

                    with st.spinner("Thinking..."):
                        response_text, _ = check_relevance_and_get_answer(prompt, st.session_state.messages, system_prompt_content)

                    st.session_state.messages.append({"role": "assistant", "content": response_text})
                    st.rerun()
                # --- END CHATBOT FIX ---


    # --- TAB 2: DEDUCTION TRACKER ---
    with tab_deductions:
        st.header("💸 Deduction Tracker")
        st.info("Track all your tax-saving expenses here. This data will be automatically used by the **Dashboard** calculator.")

        c1, c2 = st.columns([1, 2])

        with c1:
            st.subheader("Add New Deduction")
            with st.form("deduction_form", clear_on_submit=True):
                d_section = st.selectbox("Section", ["80C", "80D", "80E", "80G", "80TTA", "Other"])
                d_desc = st.text_input("Description (e.g., LIC Premium, Health Insurance)")
                d_amount = st.number_input("Amount", min_value=0.0, step=100.0)
                d_date = st.date_input("Date", datetime.date.today())

                submitted = st.form_submit_button("Add Deduction")
                if submitted:
                    # --- VALIDATION FIX ---
                    if not d_desc: # Check if description is empty
                        st.error("Description cannot be empty. Please enter a description.")
                    else:
                        try:
                            db_utils.add_deduction(username, d_section, d_desc, d_amount, d_date)
                            st.success(f"Added {d_desc} ({format_currency(d_amount)}) under {d_section}")
                            st.rerun() # Refresh to update summary chart and list immediately
                        except Exception as e:
                            st.error(f"Failed to add deduction: {e}")
                    # --- END VALIDATION FIX ---

        with c2:
            st.subheader("Your Deduction Summary")
            summary_data = db_utils.get_deductions_summary(username)
            if not summary_data:
                st.warning("No deductions added yet.")
            else:
                df_summary = pd.DataFrame(summary_data, columns=['section', 'total_amount'])

                fig = px.bar(df_summary, x='section', y='total_amount',
                             title="Your Total Claimed Deductions by Section",
                             labels={'section': 'Deduction Section', 'total_amount': 'Total Amount (Rs.)'},
                             text='total_amount')
                fig.update_traces(texttemplate='Rs. %{text:,.0f}', textposition='outside')
                st.plotly_chart(fig, use_container_width=True)

            # --- DELETION FIX ---
            with st.expander("View & Delete All Deduction Entries"):
                all_deductions = db_utils.load_deductions(username)
                if not all_deductions:
                    st.info("No individual entries found.")
                else:
                    # Create a header row using columns
                    c1, c2, c3, c4, c5 = st.columns([1.5, 3, 2, 2, 1])
                    c1.markdown("**Section**")
                    c2.markdown("**Description**")
                    c3.markdown("**Amount**")
                    c4.markdown("**Date**")
                    c5.markdown("**Action**")

                    st.divider() # Visual separator

                    # Iterate and display each deduction with a delete button
                    for deduction in all_deductions:
                        col1, col2, col3, col4, col5 = st.columns([1.5, 3, 2, 2, 1])
                        with col1:
                            st.write(deduction['section'])
                        with col2:
                            st.write(deduction['description'])
                        with col3:
                            st.write(format_currency(deduction['amount']))
                        with col4:
                            st.write(deduction['date_added'])
                        with col5:
                            # Unique key for each button using the deduction ID
                            if st.button("Delete", key=f"del_deduction_{deduction['id']}"):
                                try:
                                    db_utils.delete_deduction(deduction['id'])
                                    st.success(f"Deleted '{deduction['description']}'")
                                    st.rerun() # Refresh the page to show updated list
                                except Exception as e:
                                    st.error(f"Failed to delete: {e}")
            # --- END DELETION FIX ---

    # --- TAB 3: HRA CALCULATOR ---
    with tab_hra:
        st.header("🏠 House Rent Allowance (HRA) Exemption Calculator")
        with st.form("hra_form"):
            st.info("Fill in your salary components to calculate your HRA exemption (for Old Regime).")

            hra_basic = st.number_input("1. Your Basic Salary (Annual)", min_value=0.0, step=1000.0)
            hra_da = st.number_input("2. Dearness Allowance (DA) (Annual)", min_value=0.0, step=1000.0)
            hra_received = st.number_input("3. Total HRA Received (Annual)", min_value=0.0, step=1000.0)
            hra_rent = st.number_input("4. Total Rent Paid (Annual)", min_value=0.0, step=1000.0)

            hra_city = st.selectbox("5. City Type", ["Metro (Delhi, Mumbai, Chennai, Kolkata)", "Non-Metro"])

            hra_submitted = st.form_submit_button("Calculate HRA Exemption")
            if hra_submitted:
                city = "Metro" if "Metro" in hra_city else "Non-Metro"
                exemption = calculate_hra_exemption(hra_basic, hra_da, hra_received, hra_rent, city)
                st.success(f"Your calculated HRA exemption is: **{format_currency(exemption)}**")
                st.markdown("The *least* of the following three is your exemption:")
                st.markdown(f"1. Actual HRA Received: **{format_currency(hra_received)}**")
                st.markdown(f"2. Rent Paid minus 10% of Salary: **{format_currency(max(0, hra_rent - 0.10 * (hra_basic + hra_da)))}**")
                st.markdown(f"3. 50% (Metro) or 40% (Non-Metro) of Salary: **{format_currency(0.5 * (hra_basic + hra_da) if city == 'Metro' else 0.4 * (hra_basic + hra_da))}**")

    # --- TAB 4: CAPITAL GAINS (Simple) ---
    with tab_cap_gains:
        st.header("📈 Capital Gains Calculator (Simple)")
        st.warning("Note: This is a simplified calculator. For detailed indexation, please consult a professional.")
        with st.form("cap_gains_form"):
            cg_type = st.selectbox("Type of Asset", ["Equity (Stocks/Mutual Funds)", "Real Estate", "Other"])
            cg_buy = st.number_input("Cost of Acquisition (Buy Price)", min_value=0.0, step=1000.0)
            cg_sell = st.number_input("Full Value of Consideration (Sell Price)", min_value=0.0, step=1000.0)
            cg_holding = st.selectbox("Holding Period", ["Short Term (<= 12 months)", "Long Term (> 12 months)"])

            cg_submitted = st.form_submit_button("Calculate Gains")
            if cg_submitted:
                gains = cg_sell - cg_buy
                gain_type = "Long Term" if "Long Term" in cg_holding else "Short Term"
                if gains > 0:
                    st.success(f"Your calculated **{gain_type} Capital Gain** is: **{format_currency(gains)}**")
                else:
                    st.error(f"Your calculated **{gain_type} Capital Loss** is: **{format_currency(gains)}**")

    # --- TAB 5: AI INVESTMENT PLANNER ---
    with tab_invest:
        st.header("💡 AI-Powered Investment Planner")
        st.info("Get personalized investment suggestions based on your latest tax calculation.")

        if st.button("Generate My Investment Plan", type="primary"):
            if st.session_state.final_calc_json:
                with st.spinner("AI Advisor is analyzing your profile and market data..."):
                    data_summary = {
                        "Gross Total Income": st.session_state.final_calc_json.get("gross_total_income"),
                        "Recommended Regime": st.session_state.final_calc_json.get("recommended_regime"),
                        "Final Tax Liability": st.session_state.final_calc_json.get(f"{st.session_state.final_calc_json.get('recommended_regime', 'new').lower()}_regime_tax_liability"),
                        "Total Tax Savings": st.session_state.final_calc_json.get("tax_saving_with_recommendation"),
                        "Deductions Claimed": [dict(row) for row in db_utils.get_deductions_summary(username)]
                    }
                    advice = get_investment_advice(data_summary, investment_prompt)
                    st.markdown(advice)
            else:
                st.warning("Please run a calculation on the 'Dashboard' tab first to generate a plan.")

    # --- TAB 6: TAX CALENDAR (UPDATED) ---
    with tab_calendar:
        st.header("🗓️ Tax Calendar & Deadlines")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Add Your Custom Event")
            with st.form("add_event_form", clear_on_submit=True):
                event_title = st.text_input("Event Description")
                event_date = st.date_input("Event Date", datetime.date.today())
                submit_event = st.form_submit_button("Add Event")

                if submit_event:
                    if not event_title: # Validate title
                        st.error("Event Description cannot be empty.")
                    else:
                        try:
                            db_utils.add_user_event(username, event_title, event_date)
                            st.success(f"Added event '{event_title}' on {event_date}")
                            st.rerun() # Refresh to update lists
                        except Exception as e:
                            st.error(f"Failed to add event: {e}")

            st.divider()
            st.subheader("Your Custom Events")
            user_events = db_utils.load_user_events(username)
            if not user_events:
                st.info("You haven't added any custom events yet.")
            else:
                for event in user_events:
                    ev_col1, ev_col2 = st.columns([4, 1])
                    ev_col1.markdown(f"* **{event['start_date']}:** {event['title']}")
                    # Delete button for each user event
                    if ev_col2.button("Delete", key=f"del_event_{event['id']}"):
                        try:
                            db_utils.delete_user_event(event['id'])
                            st.success(f"Deleted event '{event['title']}'")
                            st.rerun() # Refresh lists
                        except Exception as e:
                            st.error(f"Failed to delete event: {e}")


        with col2:
            st.subheader("Important Tax Deadlines (FY 2024-25 / AY 2025-26)")
            # Using a dictionary for easier management
            static_deadlines = {
                "2025-07-31": "ITR filing deadline for individuals (non-audit).",
                "2025-06-15": "First installment of Advance Tax.",
                "2025-09-15": "Second installment of Advance Tax.",
                "2025-12-15": "Third installment of Advance Tax.",
                "2026-03-15": "Fourth (and final) installment of Advance Tax.",
                "2026-03-31": "Deadline for tax-saving investments (ELSS, PPF, etc.) for the financial year."
            }
            # Display sorted by date
            for date, desc in sorted(static_deadlines.items()):
                st.markdown(f"* **{date}:** {desc}")

        st.divider()

        # --- COMBINE STATIC AND USER EVENTS FOR THE CALENDAR WIDGET ---
        st.subheader("Full Calendar View")

        # Static events for the calendar widget
        calendar_events = [
            {"title": "ITR Filing Deadline", "start": "2025-07-31", "color": "#FF0000"}, # Red
            {"title": "Advance Tax (1st)", "start": "2025-06-15", "color": "#0000FF"}, # Blue
            {"title": "Advance Tax (2nd)", "start": "2025-09-15", "color": "#0000FF"},
            {"title": "Advance Tax (3rd)", "start": "2025-12-15", "color": "#0000FF"},
            {"title": "Advance Tax (4th)", "start": "2026-03-15", "color": "#0000FF"},
            {"title": "Tax Saving Deadline", "start": "2026-03-31", "color": "#FFA500"}, # Orange
        ]

        # Add user events to the calendar widget list
        for event in user_events:
            calendar_events.append({
                "title": event['title'],
                "start": str(event['start_date']), # Ensure it's a string
                "color": "#008000" # Green for user events
            })

        calendar_options = {
            "headerToolbar": {
                "left": "prev,next today",
                "center": "title",
                "right": "dayGridMonth,timeGridWeek,timeGridDay,listWeek",
            },
            "initialView": "dayGridMonth",
            "selectable": True, # Allows clicking on dates
        }

        # Render the calendar
        calendar(events=calendar_events, options=calendar_options, key="tax_calendar_widget")
        # --- END CALENDAR UPDATES ---

    # --- TAB 7: MY PROFILE (Save/Load) ---
    with tab_profile:
        st.header("👤 My Profile & Data")
        st.info("Export or import your user profile data.")

        try:
            profile_data = {
                "user_info": {
                    "username": username,
                    "name": name
                },
                "last_calculation": st.session_state.final_calc_json,
                "last_extracted_data": st.session_state.extracted_data,
                "tracked_deductions": [dict(row) for row in db_utils.load_deductions(username)],
                "saved_reports": [dict(row) for row in db_utils.load_calculations(username)],
                # Also include user events in export
                "user_calendar_events": [dict(row) for row in db_utils.load_user_events(username)]
            }

            st.download_button(
                label="Download My Profile Data (JSON)",
                data=json.dumps(profile_data, indent=2, default=str), # Use default=str for dates/times
                file_name=f"{username}_tax_profile.json",
                mime="application/json"
            )
        except Exception as e:
            st.error(f"Could not generate profile data: {e}")

        st.subheader("Load Profile (Coming Soon)")
        st.file_uploader("Upload your Tax Profile JSON", type="json", key="profile_uploader", disabled=True)


    # --- TAB 8: SAVED REPORTS ---
    with tab_saved:
        st.header("🗂️ Your Saved Calculation Reports")

        saved_calculations = db_utils.load_calculations(username)

        if not saved_calculations:
            st.info("You have not saved any calculations yet. Run and save a report from the 'Dashboard' tab.")
        else:
            st.markdown(f"You have **{len(saved_calculations)}** saved calculation(s).")

            for calc in saved_calculations:
                try:
                    ts = datetime.datetime.fromisoformat(calc['timestamp']).strftime('%B %d, %Y at %I:%M %p')
                    ay = calc['assessment_year']
                    regime = calc['recommended_regime']
                    savings = calc['tax_saving']
                    final_due = calc['final_amount_due']

                    exp_title = f"**{ay}** | Recommended: **{regime}** (Saved {format_currency(savings)}) | Saved on: {ts}"

                    with st.expander(exp_title):
                        st.subheader(f"Summary for {ay}")
                        if final_due < 0:
                            st.success(f"**Refund Due:** {format_currency(abs(final_due))}**")
                        elif final_due > 0:
                            st.error(f"**Tax Due:** {format_currency(final_due)}**")
                        else:
                            st.info(f"**No Tax/Refund Due**")

                        st.markdown("---")
                        st.markdown("##### Full Calculation Data")
                        st.json(json.loads(calc['calculation_data']))
                except Exception as e:
                    st.error(f"Error loading saved report: {e}")


# --- LOGIN ERROR HANDLING ---
elif authentication_status is False:
    st.error('Username/password is incorrect')
elif authentication_status is None:
    st.warning('Please enter your username and password')
# --- END APP LOGIC ---
