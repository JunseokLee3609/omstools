import sys
import time
import os
import urllib.parse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

def get_fill_metadata(fill_number):
    try:
        from omsapi import OMSAPI
        from env import CLIENT_ID, CLIENT_SECRET
        
        omsapi = OMSAPI("https://cmsoms.cern.ch/agg/api", "v1", cert_verify=False)
        omsapi.auth_oidc(CLIENT_ID, CLIENT_SECRET)
        
        query = omsapi.query("fills")
        query.filter("fill_number", fill_number)
        query.attrs(["bunches_colliding", "fill_type_runtime", "energy", "start_time"])
        query.set_verbose(False)
        
        # Fix: .data() returns a Response object, need to call .json()
        resp_json = query.data().json()
        data_list = resp_json.get("data")
        
        if data_list and len(data_list) > 0:
            data = data_list[0]
            attributes = data.get("attributes", {})
            fill_type = attributes.get("fill_type_runtime", "UNKNOWN")
            bunches = attributes.get("bunches_colliding", 0)
            start_time = attributes.get("start_time", "")
            year = start_time[:4] if start_time else "UNKNOWN"
            
            # Determine collision system (simple heuristic)
            system = "pp"
            if fill_type and ("ION" in fill_type.upper() or "PBPB" in fill_type.upper()):
                system = "PbPb"
            elif fill_type and "PROTON" in fill_type.upper():
                system = "pp"
                
            return {
                "bunches": bunches,
                "system": system,
                "type": fill_type,
                "year": year
            }
    except Exception as e:
        print(f"Warning: Could not fetch metadata for fill {fill_number}: {e}")
    
    return None

def download_plots(fill_numbers):
    #Downloads screenshots of CMS OMS fill reports for the specified fill numbers.
    output_dir = "fills"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created directory: {output_dir}")

    # Setup Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    
    # Use the CUSTOM profile we created. 
    user_data_dir = "/Users/leejunseok/chrome_debug_profile"
    chrome_options.add_argument(f"user-data-dir={user_data_dir}")
    
    print(f"Using Chrome profile at: {user_data_dir}")
    print("Initializing Chrome browser...")

    service = None
    try:
        # Install driver if needed
        driver_path = ChromeDriverManager().install()
        service = Service(driver_path)
    except Exception as e:
        print(f"Error installing driver: {e}")
        return

    try:
        # Launch Chrome automatically
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        print(f"\nError launching Chrome: {e}")
        return

    try:
        # 1. Navigate to the base URL
        base_url = "https://cmsoms.cern.ch/cms/fills/report/fullscreen/12656"
        driver.get(base_url)

        # ALWAYS pause to allow user to login if needed
        print("\n" + "="*60)
        print("WAITING FOR LOGIN")
        print("Please check the browser. If you need to log in (CERN SSO), do it now.")
        print("Once you see the page loaded, press Enter here to start downloading.")
        print("="*60 + "\n")
        input("Press Enter to continue... ")

        # Base parameters for the URL
        base_params = {
            "stable_beams": "true",
            "props.21748_12648.plots": "Delivered lumi|Recorded lumi",
            "props.21748_12648.plotbands": "downtimes",
            "props.21748_12648.plotlines": "run_starts|stable_beams",
            "props.21847_21846.plots": "B1orB2|Intensity beam 1|Intensity beam 2|beam energy|vertical crossing angle|beta* Y|beta* X",
            "props.21847_21846.plotbands": "downtimes",
            "props.21847_21846.plotlines": "run_starts|stable_beams"
        }

        for fill_number in fill_numbers:
            print(f"\nProcessing Fill {fill_number}...")
            
            # Fetch metadata
            meta = get_fill_metadata(fill_number)
            meta_str = ""
            if meta:
                meta_str = f"[{meta['year']} {meta['system']} {meta['bunches']}b]"
                print(f"Metadata: {meta_str} (Type: {meta['type']})")
            
            # Construct URL
            params = base_params.copy()
            params["cms_fill"] = str(fill_number)
            query_string = urllib.parse.urlencode(params, safe='|')
            full_url = f"{base_url}?{query_string}"
            
            # Navigate
            driver.get(full_url)
            
            # Wait for render
            wait_time = 5
            print(f"Waiting {wait_time} seconds for plots to render...")
            time.sleep(wait_time)
            
            # Inject Metadata into Page Title (Visual)
            if meta:
                # User requested Fill and Bunch count in the title
                # Format: Fill 12345 Bunches 2400 (pp 2024)
                new_title = f"Fill {fill_number} Bunches {meta['bunches']} ({meta['system']} {meta['year']})"
                
                script = f"""
                var titleEl = document.querySelector('h3') || document.querySelector('h1');
                if (titleEl) {{
                    // Prepend the new info to the existing title
                    titleEl.textContent = '{new_title} | ' + titleEl.textContent;
                    titleEl.style.color = '#d32f2f'; // Red color
                    titleEl.style.fontWeight = 'bold';
                    titleEl.style.fontSize = '1.5em';
                }}
                """
                try:
                    driver.execute_script(script)
                    print(f"Updated page title to: {new_title}")
                except Exception as e:
                    print(f"Could not update page title: {e}")
            
            filename_suffix = ""
            if meta:
                # Format: fill_12345_pp_2400b_2024.png
                filename_suffix = f"_{meta['system']}_{meta['bunches']}b_{meta['year']}"
            
            filename = os.path.join(output_dir, f"fill_{fill_number}{filename_suffix}.png")
            driver.save_screenshot(filename)
            print(f"Saved screenshot: {filename}")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        print("\nClosing browser...")
        driver.quit()

def parse_input(input_str):
    """Parses a string of fill numbers into a list of integers, ignoring comments and extra columns."""
    fills = []
    # Handle multiple lines (e.g. from file)
    lines = input_str.splitlines()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Ignore lines starting with #
        if line.startswith('#'):
            continue
            
        # Handle inline comments (e.g. "12345 # good fill")
        if '#' in line:
            line = line.split('#')[0]
            
        # Split by comma first to handle "111, 222"
        comma_parts = line.split(',')
        
        for part in comma_parts:
            part = part.strip()
            if not part:
                continue
            
            # Split by whitespace and take ONLY the first element
            # This handles "11316 1032" -> takes 11316, ignores 1032
            tokens = part.split()
            if tokens:
                try:
                    fills.append(int(tokens[0]))
                except ValueError:
                    pass
    return fills

if __name__ == "__main__":
    fill_list = []
    if len(sys.argv) > 1:
        # Check if the first argument is a file
        first_arg = sys.argv[1]
        if os.path.isfile(first_arg):
            print(f"Reading fill numbers from file: {first_arg}")
            try:
                with open(first_arg, 'r') as f:
                    input_str = f.read()
                fill_list = parse_input(input_str)
            except Exception as e:
                print(f"Error reading file: {e}")
                sys.exit(1)
        else:
            # Treat arguments as a list of numbers
            input_str = " ".join(sys.argv[1:])
            fill_list = parse_input(input_str)
    else:
        try:
            print("Enter Fill Numbers (separated by space or comma):")
            print("OR enter a filename (e.g., fills.txt):")
            user_input = input("> ")
            
            if user_input.strip():
                # Check if input is a file
                if os.path.isfile(user_input.strip()):
                    print(f"Reading fill numbers from file: {user_input.strip()}")
                    with open(user_input.strip(), 'r') as f:
                        content = f.read()
                    fill_list = parse_input(content)
                else:
                    fill_list = parse_input(user_input)
        except KeyboardInterrupt:
            sys.exit(0)

    if fill_list:
        print(f"Found {len(fill_list)} fills: {fill_list}")
        download_plots(fill_list)
    else:
        print("No valid fill numbers provided.")
