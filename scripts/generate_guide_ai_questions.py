#!/usr/bin/env python3
"""
Script to enhance Guide_Documents_Metadata_Index.json with AI-generated questions
using OpenAI to analyze guide content and create relevant questions
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
INPUT_DIR = "VECTOR_GUIDES_JSON"
INDEX_FILE = "Guide_Documents_Metadata_Index.json"

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

def load_guide_index():
    """Load the existing guide index"""
    try:
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading index file: {e}")
        return {"Guide Documents": []}

def get_guide_json(filename):
    """Load a guide JSON file"""
    json_path = os.path.join(INPUT_DIR, filename)
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading guide file {filename}: {e}")
        return None

def prepare_content_for_ai(guide_json):
    """Extract and format the most relevant content from the guide JSON"""
    content = []
    
    # Add title and guide number
    title = guide_json.get("title", "")
    guide_number = guide_json.get("guide_number", "")
    content.append(f"Guide: {title} (Number: {guide_number})")
    
    # Add sections in a structured way
    sections = guide_json.get("sections", {})
    
    # First add overview if available
    if sections.get("overview"):
        content.append(f"OVERVIEW: {sections['overview'][:1000]}")
    
    # Then add steps if available
    if sections.get("steps"):
        content.append(f"STEPS: {sections['steps'][:1500]}")
    
    # Add other sections
    for section_name, section_text in sections.items():
        if section_text and section_name not in ["overview", "steps"]:
            content.append(f"{section_name.upper()}: {section_text[:800]}")
    
    # If we don't have enough content from sections, add some of the full text
    if len(content) < 3 and guide_json.get("full_text"):
        content.append(f"CONTENT EXCERPT: {guide_json['full_text'][:2000]}")
    
    return "\n\n".join(content)

def generate_questions_with_openai(client, guide_content):
    """Generate questions using OpenAI API"""
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",  # Using a more reliable model
            messages=[
                {"role": "system", "content": "You are an expert in creating practical, user-focused questions for how-to guides, work instructions, and user guides. Your task is to identify the 3 most important questions that users would ask about this guide. Focus on specific, practical questions that staff would need answers for. Return ONLY a JSON array of 3 questions, nothing else."},
                {"role": "user", "content": guide_content}
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
                return ["How do I use this guide?", 
                        "What are the main steps I need to follow?", 
                        "What should I do if I encounter problems?"]
        except json.JSONDecodeError:
            print(f"Failed to parse JSON response: {result}")
            return ["How do I use this guide?", 
                    "What are the main steps I need to follow?", 
                    "What should I do if I encounter problems?"]
            
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return ["How do I use this guide?", 
                "What are the main steps I need to follow?", 
                "What should I do if I encounter problems?"]

def update_guide_index(index_data, client):
    """Update guide index with AI-generated questions"""
    updated_count = 0
    total_count = len(index_data["Guide Documents"])
    
    for i, guide in enumerate(index_data["Guide Documents"]):
        guide_title = guide.get("Document", "Unknown")
        
        # Display countdown and guide title
        print("\n" + "="*80)
        print(f"Processing [{i+1}/{total_count}]: {guide_title}")
        print("="*80)
        
        # Get JSON filename 
        json_filename = guide.get("File", "")
        if not json_filename or not json_filename.endswith(".json"):
            print(f"SKIPPING: Invalid filename {json_filename}")
            continue
        
        # Load the guide JSON
        guide_json = get_guide_json(json_filename)
        if not guide_json:
            print(f"SKIPPING: Could not load JSON for {json_filename}")
            continue
        
        # Prepare content for AI
        guide_content = prepare_content_for_ai(guide_json)
        
        # Generate questions
        print(f"Generating questions with OpenAI...")
        questions = generate_questions_with_openai(client, guide_content)
        
        # Display the generated questions
        print("\nGenerated questions:")
        for j, question in enumerate(questions):
            print(f"  {j+1}. {question}")
        
        # Update the guide entry
        guide["Questions Answered"] = questions
        updated_count += 1
        
        # Save after each update to prevent data loss if interrupted
        if updated_count % 5 == 0:
            save_index(index_data)
            print(f"\nSaved progress after processing {updated_count} guides")
        
        # Sleep to avoid rate limiting
        time.sleep(1)
    
    print(f"\nUpdated {updated_count} of {total_count} guides with AI-generated questions")
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
    print("Enhancing guide index with AI-generated questions...")
    
    # Backup existing index
    backup_existing_index()
    
    # Load OpenAI API key
    try:
        api_key = load_openai_key()
        client = OpenAI(api_key=api_key)
    except Exception as e:
        print(f"Failed to initialize OpenAI client: {e}")
        return
    
    # Load guide index
    index_data = load_guide_index()
    if not index_data.get("Guide Documents"):
        print("No guides found in index file")
        return
    
    # Update guide index with AI-generated questions
    updated_index = update_guide_index(index_data, client)
    
    # Save updated index
    save_index(updated_index)
    
    print("Done! All guides updated with AI-generated questions.")

if __name__ == "__main__":
    main() 