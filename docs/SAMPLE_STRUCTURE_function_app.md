import logging 

import os 

import requests 

import msal 

import azure.functions as func 

  

# --- Configuration from Application Settings --- 

TENANT_ID = os.environ.get('TENANT_ID') 

CLIENT_ID = os.environ.get('CLIENT_ID') 

CLIENT_SECRET = os.environ.get('CLIENT_SECRET') 

SHAREPOINT_SITE_NAME = os.environ.get('SHAREPOINT_SITE_NAME') # e.g., 'yourtenant.sharepoint.com' 

SHAREPOINT_LIBRARY_NAME = os.environ.get('SHAREPOINT_LIBRARY_NAME') # e.g., 'Shared Documents' 

  

# --- Microsoft Graph API Endpoints --- 

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}" 

GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0" 

SCOPE = ["https://graph.microsoft.com/.default"] 

  

# Initialize MSAL app 

app = msal.ConfidentialClientApplication( 

    client_id=CLIENT_ID, 

    authority=AUTHORITY, 

    client_credential=CLIENT_SECRET 

) 

  

# --- Main Azure Function --- 

# This example uses a timer trigger, running every 4 hours. 

# For manual execution, you could use an HTTP trigger. 

app_func = func.FunctionApp() 

  

@app_func.schedule(schedule="0 */4 * * *", arg_name="myTimer", run_on_startup=False, 

              use_monitor=False)  

def process_sharepoint_library(myTimer: func.TimerRequest) -> None: 

    logging.info('Python timer trigger function executed.') 

     

    # 1. Get Access Token 

    token_result = app.acquire_token_for_client(scopes=SCOPE) 

    if "access_token" not in token_result: 

        logging.error("Failed to acquire access token.") 

        logging.error(f"Error: {token_result.get('error')}") 

        logging.error(f"Description: {token_result.get('error_description')}") 

        return 

  

    access_token = token_result['access_token'] 

    headers = {'Authorization': f'Bearer {access_token}'} 

  

    try: 

        # 2. Get Site and Drive (Library) ID 

        site_resp = requests.get(f"{GRAPH_ENDPOINT}/sites/{SHAREPOINT_SITE_NAME}:/sites/root", headers=headers).json() 

        site_id = site_resp['id'] 

  

        drive_resp = requests.get(f"{GRAPH_ENDPOINT}/sites/{site_id}/drives", headers=headers).json() 

        library_drive_id = next((d['id'] for d in drive_resp['value'] if d['name'] == SHAREPOINT_LIBRARY_NAME), None) 

  

        if not library_drive_id: 

            logging.error(f"Library '{SHAREPOINT_LIBRARY_NAME}' not found.") 

            return 

  

        # 3. List all files recursively in the library root 

        list_files_url = f"{GRAPH_ENDPOINT}/drives/{library_drive_id}/root/children" 

         

        while list_files_url: 

            files_resp = requests.get(list_files_url, headers=headers).json() 

             

            for item in files_resp.get('value', []): 

                # We only want to process files, not folders 

                if 'file' in item: 

                    file_name = item['name'] 

                    file_id = item['id'] 

                    logging.info(f"Processing file: {file_name}") 

  

                    # 4. Download file content 

                    download_url = item.get('@microsoft.graph.downloadUrl') 

                    if download_url: 

                        file_content_response = requests.get(download_url) 

                        if file_content_response.status_code == 200: 

                            file_content = file_content_response.content 

                             

                            # 5. RUN YOUR SCRIPTS ON THE CONTENT 

                            # This is where your custom logic goes. 

                            # For example: 

                            # result1 = script1.process(file_content) 

                            # result2 = script2.analyze(result1) 

                            # final_output = result2 

                             

                            logging.info(f"Successfully processed {file_name}. Size: {len(file_content)} bytes.") 

  

                            # Optional: Upload the result back to another library or update metadata 

                            # update_metadata(headers, library_drive_id, file_id, {'status': 'processed'}) 

  

            # Check for pagination to handle libraries with >200 items 

            list_files_url = files_resp.get('@odata.nextLink') 

  

    except Exception as e: 

        logging.error(f"An error occurred: {e}") 