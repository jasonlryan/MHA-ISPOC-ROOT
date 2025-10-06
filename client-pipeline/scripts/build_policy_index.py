#!/usr/bin/env python3
"""
Script to build Policy_Documents_Metadata_Index.json from processed policy files
"""

import os
import json
import re
import shutil
from datetime import datetime
from collections import defaultdict

# Paths
INPUT_DIR = "VECTOR_JSON"
OUTPUT_FILE = "Policy_Documents_Metadata_Index.json"
EXISTING_INDEX_FILE = "Policy_Documents_Metadata_Index.json"

# Common question patterns by policy type
QUESTION_TEMPLATES = {
    # HR policies
    "HR": [
        "What are the procedures for {topic}?",
        "What are the responsibilities of managers regarding {topic}?",
        "What documentation is required for {topic}?"
    ],
    # Health and Safety policies
    "HS": [
        "What are the risk assessment requirements for {topic}?",
        "What procedures should be followed for {topic}?",
        "What training is required regarding {topic}?"
    ],
    # Clinical policies
    "CP": [
        "What are the clinical procedures for {topic}?",
        "How should {topic} incidents be reported?",
        "What are the best practices for {topic}?"
    ],
    # General policies
    "G": [
        "What is the process for handling {topic}?",
        "How should {topic} be documented?",
        "What are the key requirements for {topic}?"
    ],
    # Default for all other policy types
    "default": [
        "What are the main procedures for {topic}?",
        "What are the roles and responsibilities regarding {topic}?",
        "How should {topic} be implemented and monitored?"
    ]
}

def extract_policy_topic(title):
    """Extract the main topic from the policy title"""
    # Remove common words like "Policy", "Procedure", etc.
    common_words = ["policy", "procedure", "and", "for", "the", "of", "in", "on", "to"]
    words = title.lower().split()
    key_words = [word for word in words if word not in common_words]
    
    # Join the remaining words to form a topic
    if key_words:
        return " ".join(key_words)
    return title  # Fallback to the original title

def generate_questions(policy_id, title):
    """Generate relevant questions based on the policy type and title"""
    # Extract policy type prefix (e.g., HR, HS, CP)
    prefix_match = re.match(r'^([A-Z]+)', policy_id)
    policy_type = prefix_match.group(1) if prefix_match else "default"
    
    # Get question templates for this policy type
    templates = QUESTION_TEMPLATES.get(policy_type, QUESTION_TEMPLATES["default"])
    
    # Extract main topic
    topic = extract_policy_topic(title)
    
    # Generate questions using templates
    questions = [template.format(topic=topic) for template in templates]
    return questions

def generate_description(policy_json):
    """Generate a description based on the policy content"""
    description = ""
    
    # Try to use the purpose section if available
    if policy_json.get("sections", {}).get("purpose"):
        description = policy_json["sections"]["purpose"]
        # Truncate if too long
        if len(description) > 200:
            description = description[:197] + "..."
    
    # Fallback to summary if purpose not available
    elif policy_json.get("sections", {}).get("summary"):
        description = policy_json["sections"]["summary"]
        if len(description) > 200:
            description = description[:197] + "..."
    
    # Last resort: use the first 200 characters of full text
    elif policy_json.get("full_text"):
        description = policy_json["full_text"][:197] + "..."
    
    if not description:
        description = f"Guidelines for {policy_json.get('title', 'policy implementation')}."
    
    return description

def backup_existing_index():
    """Create a backup of the existing index file if it exists"""
    if os.path.exists(EXISTING_INDEX_FILE):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{os.path.splitext(EXISTING_INDEX_FILE)[0]}_{timestamp}.json"
        
        try:
            shutil.copy2(EXISTING_INDEX_FILE, backup_filename)
            print(f"Created backup of existing index at: {backup_filename}")
            return True
        except Exception as e:
            print(f"Warning: Could not create backup: {e}")
            return False
    
    return False

def load_existing_index():
    """Load the existing policy index if available"""
    existing_data = {"Policy Documents": []}
    if os.path.exists(EXISTING_INDEX_FILE):
        try:
            with open(EXISTING_INDEX_FILE, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load existing index: {e}")
    
    # Create a lookup by filename for easy reference
    existing_lookup = {}
    for item in existing_data.get("Policy Documents", []):
        if "File" in item:
            filename = item["File"]
            existing_lookup[filename] = item
    
    return existing_data, existing_lookup

def main():
    print(f"Building policy index from JSON files in {INPUT_DIR}...")
    
    # Backup existing index before proceeding
    backup_existing_index()
    
    # Load existing index if available
    existing_data, existing_lookup = load_existing_index()
    
    # Initialize new index
    policy_documents = []
    
    # Process each JSON file
    json_files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.json')]
    print(f"Found {len(json_files)} JSON files to process.")
    
    for json_file in json_files:
        file_path = os.path.join(INPUT_DIR, json_file)
        
        try:
            # Load JSON data
            with open(file_path, 'r', encoding='utf-8') as f:
                policy_json = json.load(f)
            
            # Extract basic info
            policy_id = policy_json.get("id", "unknown")
            title = policy_json.get("title", "")
            
            # Create output txt filename (for consistency with existing index)
            txt_filename = json_file.replace('.json', '.txt')
            
            # Check if this policy already exists in the index
            if txt_filename in existing_lookup:
                # Use existing entry but ensure it has all required fields
                entry = existing_lookup[txt_filename]
                if "Document" not in entry:
                    entry["Document"] = title
                if "Description" not in entry:
                    entry["Description"] = generate_description(policy_json)
                if "Questions Answered" not in entry:
                    entry["Questions Answered"] = generate_questions(policy_id, title)
            else:
                # Create new entry
                entry = {
                    "Document": title,
                    "File": txt_filename,
                    "Description": generate_description(policy_json),
                    "Questions Answered": generate_questions(policy_id, title)
                }
            
            policy_documents.append(entry)
            print(f"Processed: {json_file}")
            
        except Exception as e:
            print(f"Error processing {file_path}: {str(e)}")
    
    # Create final output
    output_data = {
        "Policy Documents": policy_documents
    }
    
    # Write to file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=4, ensure_ascii=False)
    
    print(f"\nIndex build complete. Created {OUTPUT_FILE} with {len(policy_documents)} policy entries.")

if __name__ == "__main__":
    main() 