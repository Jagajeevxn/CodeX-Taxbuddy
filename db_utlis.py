import sqlite3
import json
import datetime

# Use check_same_thread=False for Streamlit's threading
DB_NAME = "tax_calculations.db"

def get_db_connection():
    """Creates a database connection."""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    return conn

def create_tables():
    """Creates all necessary tables if they don't exist."""
    conn = get_db_connection()
    with conn:
        # Table 1: Stores full calculation results
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calculations (db_
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                assessment_year TEXT,
                gross_income REAL,
                recommended_regime TEXT,
                tax_saving REAL,
                final_amount_due REAL,
                calculation_data TEXT NOT NULL, -- Full JSON blob
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table 2: Tracks individual user deductions
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deductions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                section TEXT NOT NULL, -- e.g., '80C', '80D'
                description TEXT, -- e.g., 'LIC Premium', 'Health Insurance'
                amount REAL NOT NULL,
                date_added DATE
            )
        """)

        # --- NEW: Table 3: User Calendar Events ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                title TEXT NOT NULL, -- Description of the event
                start_date DATE NOT NULL
            )
        """)
        # --- END NEW ---
    conn.close()

# --- Functions for 'calculations' table ---

def save_calculation(username, calc_json):
    """Saves a calculation JSON blob for a specific user."""
    conn = get_db_connection()
    ay = calc_json.get('assessment_year', 'N/A')

    with conn:
        conn.execute(
            """
            INSERT INTO calculations
            (username, assessment_year, gross_income, recommended_regime, tax_saving, final_amount_due, calculation_data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                ay,
                calc_json.get("gross_total_income"),
                calc_json.get("recommended_regime"),
                calc_json.get("tax_saving_with_recommendation"),
                calc_json.get("final_amount_due_under_recommendation"),
                json.dumps(calc_json) # Store the full JSON
            )
        )
    conn.close()

def load_calculations(username):
    """Loads all past calculations for a specific user."""
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT * FROM calculations WHERE username = ? ORDER BY timestamp DESC",
        (username,)
    )
    calculations = cursor.fetchall()
    conn.close()
    return calculations

# --- Functions for 'deductions' table ---

def add_deduction(username, section, description, amount, date_added):
    """Adds a new individual deduction item for a user."""
    conn = get_db_connection()
    with conn:
        conn.execute(
            "INSERT INTO deductions (username, section, description, amount, date_added) VALUES (?, ?, ?, ?, ?)",
            (username, section, description, amount, date_added)
        )
    conn.close()

def load_deductions(username):
    """Loads all individual deductions for a user."""
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT * FROM deductions WHERE username = ? ORDER BY section, date_added DESC",
        (username,)
    )
    deductions = cursor.fetchall()
    conn.close()
    return deductions

def get_deductions_summary(username):
    """Gets the sum of deductions grouped by section."""
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT section, SUM(amount) as total_amount FROM deductions WHERE username = ? GROUP BY section",
        (username,)
    )
    summary = cursor.fetchall()
    conn.close()
    return summary

def delete_deduction(deduction_id):
    """Deletes a specific deduction entry by its ID."""
    conn = get_db_connection()
    with conn:
        conn.execute(
            "DELETE FROM deductions WHERE id = ?",
            (deduction_id,)
        )
    conn.close()

# --- NEW Functions for 'user_events' table ---

def add_user_event(username, title, start_date):
    """Adds a custom calendar event for a user."""
    conn = get_db_connection()
    with conn:
        conn.execute(
            "INSERT INTO user_events (username, title, start_date) VALUES (?, ?, ?)",
            (username, title, start_date)
        )
    conn.close()

def load_user_events(username):
    """Loads all custom calendar events for a user."""
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT * FROM user_events WHERE username = ? ORDER BY start_date",
        (username,)
    )
    events = cursor.fetchall()
    conn.close()
    return events

def delete_user_event(event_id):
    """Deletes a specific user event by its ID."""
    conn = get_db_connection()
    with conn:
        conn.execute(
            "DELETE FROM user_events WHERE id = ?",
            (event_id,)
        )
    conn.close()
# --- END NEW ---
