# 🤖 AI TaxBuddy by CodeX: Automated Tax Filing & Optimization

AI TaxBuddy is a cutting-edge web application designed to automate the complex process of Indian Income Tax Return (ITR) filing. Leveraging the power of the **Gemini API**, it transforms unstructured financial documents (like Form 16) into structured, submission-ready data, calculates the optimized tax liability, and provides an expert conversational agent for tax queries.

Built with **Streamlit** for the frontend and a **Chain-of-Prompts** architecture for the backend logic, AI TaxBuddy showcases the power of multimodal AI in FinTech automation.

## ✨ Key Features
| Feature | Description | AI Technology Used |
| :--- | :--- | :--- |
| **Multimodal Data Extraction** | Gets a **Form 16** (PDF/Image) from the user, uses Gemini to read the visual data, and converts it into a clean, structured JSON object. | `gemini-2.5-pro` (Multimodal) & Forced JSON Output. |
| **Dual Regime Optimization** | Calculates tax liability under **both the Old Tax Regime and the New Tax Regime** (implicitly modeled in the prompt's CoT) and compares them to find the lowest tax payable or maximum refund. | Chain-of-Thought (CoT) & Rule-Based RAG via Prompting. |
| **Submission-Ready Form Generation**| Takes the final, optimized tax figures and maps them directly to the fields of an **ITR-1** schema, resulting in a downloadable JSON file ready for digital submission. | Structured Output Prompting & Data Mapping. |
| **Interactive Chat Agent** | Allows users to chat with the AI to ask relevant questions about their tax details, deductions, or general ITR filing procedure. | Contextual Conversation & Safety Filtering. |
| **Contextual Relevance** | The system rejects questions that are not related to taxation, ensuring the chatbot remains focused and professional (as per the application logic's intent). | System Prompt & Safety Configurations. |

## 🧠 The "Chain-of-Prompts" Architecture

The core of this project is chaining three specialized Gemini agents to handle the workflow:

1.  **TaxScan (Extractor):** Reads **Form 16** (Image/PDF) -> Outputs **Raw JSON Data**.
2.  **TaxLogic (Calculator):** Takes **Raw JSON** -> Applies **Dual Regime Rules** -> Outputs **CoT Calculation & Final Summary JSON**.
3.  **FormGen (Generator):** Takes **Final Summary JSON** -> Maps to **ITR-1 Schema** -> Outputs **Submission-Ready ITR JSON**.

## 🛠️ Tech Stack

* **Frontend/Web App:** Python's **Streamlit**
* **AI Backend:** **Gemini API** (`google-generativeai`)
* **Core Models:** `gemini-2.5-pro` (for high-fidelity multimodal and complex reasoning tasks)
* **Language:** Python
* **Deployment:** Hosted via Streamlit Community Cloud (URL: `https://codex-taxbuddy.streamlit.app/`)

## 🚀 How to Run Locally

1.  **Clone the repository (or set up your project folder):**
    ```bash
    git clone [YOUR_GITHUB_REPO_URL]
    cd [YOUR_GITHUB_REPO_NAME]
    ```

2.  **Install the dependencies:**
    ```bash
    pip install streamlit google-generativeai Pillow
    ```

3.  **Set your API Key Securely:**
    * Get a free API key from Google AI Studio.
    * Create a folder named `.streamlit` in your project directory.
    * Inside `.streamlit`, create a file named `secrets.toml` and add your key:
        ```toml
        GOOGLE_API_KEY = "YOUR_API_KEY_HERE"
        ```

4.  **Run the application:**
    ```bash
    streamlit run app.py
    ```
    The application will open in your browser at `localhost:8501`.
