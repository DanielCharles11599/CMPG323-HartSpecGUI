import py_compile
from pathlib import Path

# List of expected scientific modules and their purposes as per SARAO specifications
EXPECTED_MODULES = {
    "File_check.py": "Main entry: reads FITS files & sorts them into observation blocks",
    "Interact.py": "CLI menu for source and frequency directory selection",
    "load_file.py": "Primary FITS loader (extracts 30+ header fields)",
    "load_file2.py": "Alternate FITS loader for standard/unconventional headers",
    "File_Manage.py": "Identifies, logs, and isolates corrupted FITS datasets",
    "Baseline.py": "Bandpass correction (Frequency-switch & Position-switch)",
    "Blocks.py": "Interactive baseline region selection (defines velocity blocks)",
    "Flat_base.py": "Polynomial baseline subtraction using masked arrays",
    "Cal_point_check.py": "Pointing correction calibration (frequency-switched)",
    "Cal_point_cor.py": "Pointing correction calibration (position-switched)",
    "Point_cor.py": "Calculates pointing correction factor & coordinates offsets",
    "fit_max.py": "Polynomial peak finder fitting over a velocity window",
    "Calibrate_PSS_PWR.py": "PSS database lookup & atmospheric attenuation calculations",
    "Obs_Point_Full.py": "Coordinates full on-source data reduction sequence",
    "Option.py": "User selection options (Auto/Manual depth control)",
    "Gaussf.py": "One-dimensional Gaussian fit with fixed HPBW limits",
    "2D_Gauss_fit.py": "Two-dimensional rotated Gaussian model optimization",
    "Spec_comp.py": "Multi-component Gaussian decomposition (subtract-and-fit loop)",
    "plot_spec.py": "Generates, labels, and saves publication-quality spectra plots",
    "HARTRAO.py": "Main dispatcher option loop for pipeline modules"
}


def check_clc_modules():
    print("==================================================")
    print("🔭 HARTSPEC CLC: SCIENTIFIC MODULES VERIFIER")
    print("==================================================")

    # Resolve clc folder path relative to script location
    root_dir = Path(__file__).resolve().parent
    clc_dir = root_dir / "clc"

    if not clc_dir.exists() or not clc_dir.is_dir():
        print(f"❌ ERROR: Could not find a 'clc' folder at: {clc_dir}")
        print("   Please ensure that your physical 'clc' folder (containing the")
        print("   original scientific Python files) is placed in your repository root.")
        return

    print(f"✅ Found physical 'clc' folder directory at: {clc_dir}\n")

    missing_count = 0
    syntax_error_count = 0
    passed_count = 0

    print(f"{'File Name':<25} | {'Exist':<6} | {'Syntax':<8} | Purpose")
    print("-" * 110)

    for filename, description in EXPECTED_MODULES.items():
        file_path = clc_dir / filename
        exists = file_path.exists()
        syntax_ok = "N/A"

        if exists:
            # Check if file compiles correctly (no broken syntax)
            try:
                py_compile.compile(str(file_path), doraise=True)
                syntax_ok = "✅ PASS"
                passed_count += 1
            except py_compile.PyCompileError as e:
                syntax_ok = "❌ FAIL"
                syntax_error_count += 1
            except Exception:
                syntax_ok = "⚠️ WARN"
        else:
            exists_str = "❌ NO"
            missing_count += 1

        exists_str = "✅ YES" if exists else "❌ NO"
        print(f"{filename:<25} | {exists_str:<6} | {syntax_ok:<8} | {description}")

    print("-" * 110)
    print("========================= SUMMARY =========================")
    print(f"Total Required Modules Checked : {len(EXPECTED_MODULES)}")
    print(f"Successfully Located & Parsed  : {passed_count}")
    
    if missing_count > 0:
        print(f"❌ Missing Modules             : {missing_count} (Check your Google Drive download!)")
    if syntax_error_count > 0:
        print(f"❌ Syntax/Compilation Failures  : {syntax_error_count} (Incompatible with current environment)")
        
    print("==================================================")

    if missing_count == 0 and syntax_error_count == 0:
        print("🎉 SUCCESS! Your 'clc' folder is completely set up and ready.")
        print("   All scientific modules are present and syntactically clean.")
    else:
        print("⚠️  ACTION REQUIRED: Please verify and resolve the issues flagged above.")

if __name__ == "__main__":
    check_clc_modules()
    