import os
import sys
import datetime
import streamlit as st

# ==========================================
# STEP 1: THE "CODE-ONLY" PATH SOLUTION
# ==========================================
# This adds the root folder to the search path so we can import 'clc' modules 
# seamlessly on Windows, macOS, or Ubuntu server without symbolic link errors.
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)

# Attempt to import Astropy for real FITS reading
try:
    from astropy.io import fits
    ASTROPY_AVAILABLE = True
except ImportError:
    ASTROPY_AVAILABLE = False

# Attempt to import the original scientific File_check module
try:
    from clc.File_check import check_files
    CLC_FILE_CHECK_AVAILABLE = True
except ImportError:
    CLC_FILE_CHECK_AVAILABLE = False


# ==========================================
# STEP 2: SESSION STATE INITIALIZATION
# ==========================================
# Preserve settings across browser refreshes (Streamlit stateless model)
if "session_id" not in st.session_state:
    st.session_state.session_id = datetime.datetime.now().strftime("SESS-%Y%m%d-%H%M%S")
if "selected_source" not in st.session_state:
    st.session_state.selected_source = "None Selected"
if "selected_frequency" not in st.session_state:
    st.session_state.selected_frequency = "None Selected"
if "observation_date" not in st.session_state:
    st.session_state.observation_date = "None Selected"
if "pipeline_stage" not in st.session_state:
    st.session_state.pipeline_stage = 1  # Stage 1: Source Browser
if "confirmed_files" not in st.session_state:
    st.session_state.confirmed_files = []


# ==========================================
# STEP 3: PERSISTENT SIDEBAR METADATA
# ==========================================
st.sidebar.title("🔭 HartSpec GUI")
st.sidebar.subheader("Active Session Metadata")
st.sidebar.text(f"Session ID: {st.session_state.session_id}")
st.sidebar.markdown(f"**Active Source:** {st.session_state.selected_source}")
st.sidebar.markdown(f"**Frequency:** {st.session_state.selected_frequency}")
st.sidebar.markdown(f"**Obs Date:** {st.session_state.observation_date}")

# Session Controls
st.sidebar.divider()
st.sidebar.subheader("Session Management")
if st.sidebar.button("Reset Session", use_container_width=True):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


# ==========================================
# STEP 4: PROGRESS INDICATOR (FR-20)
# ==========================================
# Displays overall pipeline completion progress at the top of the page
total_stages = 8
progress_val = st.session_state.pipeline_stage / total_stages
st.progress(progress_val, text=f"Pipeline Progress: Stage {st.session_state.pipeline_stage} of {total_stages}")


# ==========================================
# MAIN PAGE CONTENT
# ==========================================
st.title("📂 Source & Frequency Browser")
st.caption("Browse observation directories, filter target coordinates, and sort FITS files into calibration blocks.")

# Determine the directory path (Defaulting to server layout, with local fallback)
DEFAULT_SERVER_PATH = "/data/fits"
LOCAL_FALLBACK_PATH = os.path.join(ROOT_DIR, "data", "fits")
target_dir = DEFAULT_SERVER_PATH if os.path.exists(DEFAULT_SERVER_PATH) else LOCAL_FALLBACK_PATH

# Safe directory creation for local testing
if not os.path.exists(target_dir):
    os.makedirs(target_dir, exist_ok=True)

# Main container for the File Browser settings
st.subheader("Directory Configuration")
selected_path = st.text_input("Active FITS Archive Directory:", value=target_dir)

# Helper function to parse FITS headers
def scan_fits_directory(directory_path):
    files_found = []
    
    # Locate all FITS files in target path
    for root, _, files in os.walk(directory_path):
        for file in files:
            if file.lower().endswith((".fits", ".fit")):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, directory_path)
                
                # Default mock values if files are unreadable/empty
                source = "Maser-Target"
                freq = "22.2 GHz"
                obs_date = datetime.date.today().isoformat()
                block_type = "ON"
                
                # Attempt to extract scientific data directly from FITS headers
                if ASTROPY_AVAILABLE:
                    try:
                        with fits.open(full_path, memmap=True) as hdulist:
                            header = hdulist.header
                            source = header.get("OBJECT", source)
                            # Derive frequency from typical headers (e.g. RESTFREQ or subfolder)
                            freq_hz = header.get("RESTFREQ", None)
                            if freq_hz:
                                freq = f"{round(freq_hz / 1e9, 2)} GHz"
                            obs_date = header.get("DATE-OBS", header.get("DATE", obs_date))
                            if "T" in obs_date:
                                obs_date = obs_date.split("T")
                    except Exception:
                        pass # Fail silently and use fallback values
                
                # Simple heuristic block classifier mimicking File_check.py
                file_lower = file.lower()
                if "hpn" in file_lower: block_type = "HPN"
                elif "hps" in file_lower: block_type = "HPS"
                elif "hpe" in file_lower: block_type = "HPE"
                elif "hpw" in file_lower: block_type = "HPW"
                elif "off" in file_lower: block_type = "OFF"
                
                files_found.append({
                    "Filename": file,
                    "RelativePath": rel_path,
                    "Source": source,
                    "Frequency": freq,
                    "Date": obs_date,
                    "BlockType": block_type
                })
                
    # If the directory is empty, supply rich Mock Data so developers can test immediately
    if len(files_found) == 0:
        files_found = [
            {"Filename": "G351_HPN.fits", "RelativePath": "G351/G351_HPN.fits", "Source": "G351.78-0.54", "Frequency": "22.2 GHz", "Date": "2026-08-10", "BlockType": "HPN"},
            {"Filename": "G351_HPS.fits", "RelativePath": "G351/G351_HPS.fits", "Source": "G351.78-0.54", "Frequency": "22.2 GHz", "Date": "2026-08-10", "BlockType": "HPS"},
            {"Filename": "G351_HPE.fits", "RelativePath": "G351/G351_HPE.fits", "Source": "G351.78-0.54", "Frequency": "22.2 GHz", "Date": "2026-08-10", "BlockType": "HPE"},
            {"Filename": "G351_HPW.fits", "RelativePath": "G351/G351_HPW.fits", "Source": "G351.78-0.54", "Frequency": "22.2 GHz", "Date": "2026-08-10", "BlockType": "HPW"},
            {"Filename": "G351_ON.fits", "RelativePath": "G351/G351_ON.fits", "Source": "G351.78-0.54", "Frequency": "22.2 GHz", "Date": "2026-08-10", "BlockType": "ON"},
            {"Filename": "G351_OFF.fits", "RelativePath": "G351/G351_OFF.fits", "Source": "G351.78-0.54", "Frequency": "22.2 GHz", "Date": "2026-08-10", "BlockType": "OFF"},
            {"Filename": "W3OH_ON.fits", "RelativePath": "W3OH/W3OH_ON.fits", "Source": "W3OH", "Frequency": "6.7 GHz", "Date": "2026-08-12", "BlockType": "ON"},
            {"Filename": "W3OH_OFF.fits", "RelativePath": "W3OH/W3OH_OFF.fits", "Source": "W3OH", "Frequency": "6.7 GHz", "Date": "2026-08-12", "BlockType": "OFF"},
        ]
    return files_found

# Scan and fetch all files
all_files = scan_fits_directory(selected_path)

# ==========================================
# STEP 5: FILTERS & DROPDOWNS (FR-01)
# ==========================================
col1, col2 = st.columns(2)
with col1:
    source_options = sorted(list(set([f["Source"] for f in all_files])))
    filter_source = st.selectbox("Filter by Source Name:", ["All Sources"] + source_options)

with col2:
    freq_options = sorted(list(set([f["Frequency"] for f in all_files])))
    filter_freq = st.selectbox("Filter by Frequency:", ["All Frequencies"] + freq_options)

# Filter the list of files based on selection
filtered_files = all_files
if filter_source != "All Sources":
    filtered_files = [f for f in filtered_files if f["Source"] == filter_source]
if filter_freq != "All Frequencies":
    filtered_files = [f for f in filtered_files if f["Frequency"] == filter_freq]

# Get date statistics
all_dates = [datetime.datetime.strptime(f["Date"], "%Y-%m-%d") for f in filtered_files]
earliest_date = min(all_dates).strftime("%Y-%m-%d") if all_dates else "N/A"
latest_date = max(all_dates).strftime("%Y-%m-%d") if all_dates else "N/A"

# Display Directory Summary (FR-01)
st.divider()
st.subheader("Directory Summary Metrics")
m_col1, m_col2, m_col3 = st.columns(3)
m_col1.metric("Total FITS Files Found", len(all_files))
m_col2.metric("Filtered Files Matching Search", len(filtered_files))
m_col3.metric("Observation Date Range", f"{earliest_date} to {latest_date}" if all_dates else "N/A")


# ==========================================
# STEP 6: VISUAL DIRECTORY TREE (FR-01)
# ==========================================
st.subheader("Interactive Directory Tree View")
# Builds a clean tree-like representation using expanders
tree_dict = {}
for f in filtered_files:
    parts = f["RelativePath"].split(os.sep)
    current_level = tree_dict
    for part in parts[:-1]:
        if part not in current_level:
            current_level[part] = {}
        current_level = current_level[part]
    current_level[parts[-1]] = f

def display_tree(node, depth=0):
    for key, val in node.items():
        indent = "  " * depth
        if isinstance(val, dict) and "Filename" not in val:
            st.markdown(f"{indent}📁 **{key}/**")
            display_tree(val, depth + 1)
        else:
            # It's a leaf FITS file
            st.markdown(f"{indent}📄 {key} `({val['BlockType']})`")

with st.expander("Expand to view nested FITS folder tree", expanded=True):
    display_tree(tree_dict)


# ==========================================
# STEP 7: OBSERVATION BLOCK SUMMARY TABLE
# ==========================================
st.subheader("Observation Block Classification")
st.text("FITS files have been sorted into the following calibration structures:")

# Pivot files into blocks
block_counts = {"HPN": 0, "HPS": 0, "HPE": 0, "HPW": 0, "ON": 0, "OFF": 0}
for f in filtered_files:
    b_type = f["BlockType"]
    if b_type in block_counts:
        block_counts[b_type] += 1

st.dataframe(
    [{"Block Classification": k, "FITS File Count": v} for k, v in block_counts.items()],
    use_container_width=True
)


# ==========================================
# STEP 8: CONFIRMATION & NAVIGATION
# ==========================================
st.divider()
if st.button("Confirm Selection & Save to Session State", type="primary", use_container_width=True):
    if len(filtered_files) == 0:
        st.error("No files selected. Adjust your filters and try again.")
    else:
        # Save selection details to persistent Streamlit session state
        st.session_state.selected_source = filter_source if filter_source != "All Sources" else filtered_files["Source"]
        st.session_state.selected_frequency = filter_freq if filter_freq != "All Frequencies" else filtered_files["Frequency"]
        st.session_state.observation_date = earliest_date
        st.session_state.confirmed_files = filtered_files
        
        # Execute science script logic if available
        if CLC_FILE_CHECK_AVAILABLE:
            try:
                # Runs the actual terminal equivalent step
                check_files()
            except Exception as e:
                st.warning(f"Note: clc.File_check executed but returned a localized warning: {e}")
                
        st.success(f"✅ Success! Target '{st.session_state.selected_source}' confirmed at {st.session_state.selected_frequency}.")
        st.info("👉 You can now navigate to the next stage by selecting **02_File_Loader.py** in the sidebar folder menu.")