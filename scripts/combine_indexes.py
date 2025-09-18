#!/usr/bin/env python3

import json
import os
import sys

def combine_indexes():
    """
    Combines the Guide and Policy indexes into one MHA Documents index.
    Ensures all file extensions are .json and adds Document Type field.
    """
    print("Starting index combination process...")
    
    # Define file paths
    guide_index_path = 'Guide_Documents_Metadata_Index.json'
    policy_index_path = 'Policy_Documents_Metadata_Index.json'
    output_index_path = 'MHA_Documents_Metadata_Index.json'
    
    # Check if input files exist
    if not os.path.exists(guide_index_path):
        print(f"Error: {guide_index_path} not found")
        sys.exit(1)
    
    if not os.path.exists(policy_index_path):
        print(f"Error: {policy_index_path} not found")
        sys.exit(1)
    
    # Load guide index
    with open(guide_index_path, 'r', encoding='utf-8') as f:
        try:
            guide_data = json.load(f)
            print(f"Successfully loaded {guide_index_path}")
        except json.JSONDecodeError as e:
            print(f"Error loading {guide_index_path}: {e}")
            sys.exit(1)
    
    # Load policy index
    with open(policy_index_path, 'r', encoding='utf-8') as f:
        try:
            policy_data = json.load(f)
            print(f"Successfully loaded {policy_index_path}")
        except json.JSONDecodeError as e:
            print(f"Error loading {policy_index_path}: {e}")
            sys.exit(1)
    
    # Create combined structure
    combined_data = {
        "MHA Documents": []
    }
    
    # Process guide documents
    guide_count = 0
    for doc in guide_data.get("Guide Documents", []):
        # Ensure file ends with .json
        if "File" in doc:
            # Replace .txt with .json if present
            if doc["File"].endswith(".txt"):
                doc["File"] = doc["File"].replace(".txt", ".json")
            # Add .json if no extension
            elif not doc["File"].endswith(".json"):
                doc["File"] += ".json"
        
        # Add Document Type if not present
        if "Document Type" not in doc:
            doc["Document Type"] = "Guide"
        
        combined_data["MHA Documents"].append(doc)
        guide_count += 1
    
    # Process policy documents
    policy_count = 0
    for doc in policy_data.get("Policy Documents", []):
        # Ensure file ends with .json
        if "File" in doc:
            # Replace .txt with .json if present
            if doc["File"].endswith(".txt"):
                doc["File"] = doc["File"].replace(".txt", ".json")
            # Add .json if no extension
            elif not doc["File"].endswith(".json"):
                doc["File"] += ".json"
        
        # Add Document Type if not present
        if "Document Type" not in doc:
            doc["Document Type"] = "Policy"
        
        combined_data["MHA Documents"].append(doc)
        policy_count += 1
    
    # Save the combined index
    with open(output_index_path, 'w', encoding='utf-8') as f:
        json.dump(combined_data, f, indent=4, ensure_ascii=False)
    
    print(f"Combined index created successfully at {output_index_path}")
    print(f"Added {guide_count} guides and {policy_count} policies")
    print(f"Total documents: {guide_count + policy_count}")
    
    # Verify the output file
    print("Verifying output file...")
    try:
        with open(output_index_path, 'r', encoding='utf-8') as f:
            verification_data = json.load(f)
            
        # Check for missing .json extensions
        missing_json = [doc["File"] for doc in verification_data["MHA Documents"] 
                        if "File" in doc and not doc["File"].endswith(".json")]
        
        # Check for missing Document Type
        missing_type = [doc["Document"] for doc in verification_data["MHA Documents"] 
                        if "Document Type" not in doc]
        
        if missing_json:
            print(f"Warning: {len(missing_json)} files still don't have .json extension")
            for file in missing_json[:5]:  # Show first 5 examples
                print(f"  - {file}")
            if len(missing_json) > 5:
                print(f"  - ... and {len(missing_json) - 5} more")
        else:
            print("✅ All files have .json extension")
            
        if missing_type:
            print(f"Warning: {len(missing_type)} documents are missing Document Type")
            for doc in missing_type[:5]:  # Show first 5 examples
                print(f"  - {doc}")
            if len(missing_type) > 5:
                print(f"  - ... and {len(missing_type) - 5} more")
        else:
            print("✅ All documents have Document Type field")
            
        if not missing_json and not missing_type:
            print("✅ Verification successful! All requirements met.")
        
    except Exception as e:
        print(f"Error during verification: {e}")

if __name__ == "__main__":
    combine_indexes() 