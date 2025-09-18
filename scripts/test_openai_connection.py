#!/usr/bin/env python3
"""
Script to test OpenAI API connection
"""

import os
import dotenv
from openai import OpenAI

# Path to .env file
ENV_FILE = "iSPOC/.env"

def main():
    print("Testing OpenAI API connection...")
    
    # Load .env file
    print(f"Loading .env file from: {ENV_FILE}")
    dotenv.load_dotenv(ENV_FILE)
    
    # Get API key
    api_key = os.getenv("VITE_OPENAI_API_KEY")
    if not api_key:
        print("ERROR: No OpenAI API key found in .env file")
        return
    
    # Print masked API key
    masked_key = api_key[:4] + "..." + api_key[-4:]
    print(f"Found API key: {masked_key}")
    
    try:
        # Initialize client
        print("Initializing OpenAI client...")
        client = OpenAI(api_key=api_key)
        
        # Test API with a simple completion
        print("Testing API with a simple completion...")
        response = client.chat.completions.create(
            model="gpt-4.1-mini",  # Using a simpler model for testing
            messages=[
                {"role": "user", "content": "Hello, can you hear me? Respond with a single word."}
            ],
            max_tokens=10
        )
        
        # Print result
        result = response.choices[0].message.content
        print(f"Response from OpenAI: '{result}'")
        print("API connection test SUCCESSFUL!")
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        
if __name__ == "__main__":
    main() 