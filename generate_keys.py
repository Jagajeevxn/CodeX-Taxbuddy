import bcrypt
import sys

print("--- Running Radical Hasher (using bcrypt directly) ---")

# 1. List your desired passwords
passwords_to_hash = ["user1_pass", "user2_pass"]

try:
    hashed_passwords_list = []
    
    for password in passwords_to_hash:
        # 2. Encode the password to bytes
        password_bytes = password.encode('utf-8')
        
        # 3. Generate the salt and hash the password
        salt = bcrypt.gensalt()
        hashed_bytes = bcrypt.hashpw(password_bytes, salt)
        
        # 4. Decode the hash back to a string for the YAML file
        hashed_string = hashed_bytes.decode('utf-8')
        hashed_passwords_list.append(hashed_string)

    # 5. Print the final list
    print("\n--- SUCCESS! ---")
    print("Your bcrypt-hashed passwords are:")
    print(hashed_passwords_list)
    
    print("\nCopy this list and paste it into your .streamlit/config.yaml")

except Exception as e:
    print(f"\n--- SCRIPT FAILED ---")
    print(f"Error: {e}")
    if "No module named 'bcrypt'" in str(e):
        print("\n**ACTION REQUIRED:** Please run 'pip install bcrypt' and try again.")
    else:
        print("\nAn unexpected error occurred. Please check your Python installation.")
