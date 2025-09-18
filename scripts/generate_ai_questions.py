#!/usr/bin/env python3
"""
Script to enhance Policy_Documents_Metadata_Index.json with AI-generated questions
using OpenAI to analyze policy content and create relevant questions
"""

import os
import json
import time
import re
import dotenv
from openai import OpenAI
from datetime import datetime
import shutil

# Paths
ENV_FILE = "iSPOC/.env"
INPUT_DIR = "VECTOR_JSON"
INDEX_FILE = "Policy_Documents_Metadata_Index.json"

def backup_existing_index():
    """Create a backup of the existing index file"""
    if os.path.exists(INDEX_FILE):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{os.path.splitext(INDEX_FILE)[0]}_{timestamp}.json"
        
        try:
            shutil.copy2(INDEX_FILE, backup_filename)
            print(f"Created backup of existing index at: {backup_filename}")
            return True
        except Exception as e:
            print(f"Warning: Could not create backup: {e}")
            return False
    return False

def load_openai_key():
    """Load OpenAI API key from .env file"""
    dotenv.load_dotenv(ENV_FILE)
    api_key = os.getenv("VITE_OPENAI_API_KEY")
    if not api_key:
        raise ValueError("No OpenAI API key found in .env file")
    return api_key

def load_policy_index():
    """Load the existing policy index"""
    try:
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading index file: {e}")
        return {"Policy Documents": []}

def get_policy_json(filename):
    """Load a policy JSON file"""
    json_path = os.path.join(INPUT_DIR, filename)
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading policy file {filename}: {e}")
        return None

def prepare_content_for_ai(policy_json):
    """Extract and format the most relevant content from the policy JSON"""
    content = []
    
    # Add title and ID
    title = policy_json.get("title", "")
    policy_id = policy_json.get("id", "")
    content.append(f"Policy: {title} (ID: {policy_id})")
    
    # Add sections in a structured way
    sections = policy_json.get("sections", {})
    for section_name, section_text in sections.items():
        if section_text:
            content.append(f"{section_name.upper()}: {section_text[:1000]}")  # Limit each section
    
    # If we don't have enough content from sections, add some of the full text
    if len(content) < 3 and policy_json.get("full_text"):
        content.append(f"CONTENT EXCERPT: {policy_json['full_text'][:2000]}")
    
    return "\n\n".join(content)

def generate_questions_with_openai(client, policy_content):
    """Generate questions using OpenAI API"""
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",  # Using a more reliable model
            messages=[
                {"role": "system", "content": "You are an expert in healthcare policy analysis. Your task is to identify the 3 most important questions that this policy answers. Focus on specific, practical questions that staff would need to know. Return ONLY a JSON array of 3 questions, nothing else."},
                {"role": "user", "content": policy_content}
            ],
            response_format={"type": "json_object"},
            temperature=0.5,
            max_tokens=500
        )
        
        result = response.choices[0].message.content
        # Parse the JSON response to extract the questions
        try:
            questions_data = json.loads(result)
            if "questions" in questions_data:
                return questions_data["questions"]
            else:
                # Sometimes the model returns an array directly
                if isinstance(questions_data, list):
                    return questions_data
                # Or it might use a different key
                for key in questions_data:
                    if isinstance(questions_data[key], list) and len(questions_data[key]) > 0:
                        return questions_data[key][:3]  # Ensure we only take 3 questions
                return ["What procedures are outlined in this policy?", 
                        "What are the key responsibilities defined in this policy?", 
                        "How is compliance with this policy monitored?"]
        except json.JSONDecodeError:
            print(f"Failed to parse JSON response: {result}")
            return ["What procedures are outlined in this policy?", 
                    "What are the key responsibilities defined in this policy?", 
                    "How is compliance with this policy monitored?"]
            
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return ["What procedures are outlined in this policy?", 
                "What are the key responsibilities defined in this policy?", 
                "How is compliance with this policy monitored?"]

def update_policy_index(index_data, client):
    """Update policy index with AI-generated questions"""
    updated_count = 0
    total_count = len(index_data["Policy Documents"])
    
    for i, policy in enumerate(index_data["Policy Documents"]):
        policy_title = policy.get("Document", "Unknown")
        
        # Display countdown and policy title
        print("\n" + "="*80)
        print(f"Processing [{i+1}/{total_count}]: {policy_title}")
        print("="*80)
        
        # Extract JSON filename from the txt filename
        txt_filename = policy.get("File", "")
        if not txt_filename or not txt_filename.endswith(".txt"):
            print(f"SKIPPING: Invalid filename {txt_filename}")
            continue
            
        json_filename = txt_filename.replace(".txt", ".json")
        
        # Load the policy JSON
        policy_json = get_policy_json(json_filename)
        if not policy_json:
            print(f"SKIPPING: Could not load JSON for {json_filename}")
            continue
        
        # Prepare content for AI
        policy_content = prepare_content_for_ai(policy_json)
        
        # Generate questions
        print(f"Generating questions with OpenAI...")
        questions = generate_questions_with_openai(client, policy_content)
        
        # Display the generated questions
        print("\nGenerated questions:")
        for j, question in enumerate(questions):
            print(f"  {j+1}. {question}")
        
        # Update the policy entry
        policy["Questions Answered"] = questions
        updated_count += 1
        
        # Save after each update to prevent data loss if interrupted
        if updated_count % 5 == 0:
            save_index(index_data)
            print(f"\nSaved progress after processing {updated_count} policies")
        
        # Sleep to avoid rate limiting
        time.sleep(1)
    
    print(f"\nUpdated {updated_count} of {total_count} policies with AI-generated questions")
    return index_data

def save_index(index_data):
    """Save the updated index back to file"""
    try:
        with open(INDEX_FILE, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving index file: {e}")
        return False

def main():
    print("Enhancing policy index with AI-generated questions...")
    
    # Backup existing index
    backup_existing_index()
    
    # Load OpenAI API key
    try:
        api_key = load_openai_key()
        client = OpenAI(api_key=api_key)
    except Exception as e:
        print(f"Failed to initialize OpenAI client: {e}")
        return
    
    # Load policy index
    index_data = load_policy_index()
    if not index_data.get("Policy Documents"):
        print("No policies found in index file")
        return
    
    # Update policy index with AI-generated questions
    updated_index = update_policy_index(index_data, client)
    
    # Save updated index
    save_index(updated_index)
    
    print("Done! All policies updated with AI-generated questions.")

if __name__ == "__main__":
    main() 