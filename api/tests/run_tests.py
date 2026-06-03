import os
import sys
import subprocess

def run_cmd(args):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(args, env=env, capture_output=True, text=True)
    return result

def main():
    test_files = [
        "tests/test_phase1.py",
        "tests/test_peripherals.py",
        "tests/test_heartbeat.py",
        "tests/test_telemetry.py",
        "tests/test_command.py"
    ]
    
    print("=== Running Backend Integration Tests ===")
    
    python_exe = sys.executable
    
    failed = False
    for test_file in test_files:
        print(f"\nFlushing database before {test_file}...")
        flush_res = run_cmd([python_exe, "manage.py", "flush", "--no-input"])
        if flush_res.returncode != 0:
            print(f"Failed to flush database: {flush_res.stderr}")
            failed = True
            break
            
        print(f"Running {test_file}...")
        test_res = run_cmd([python_exe, test_file])
        print(test_res.stdout)
        if test_res.returncode != 0:
            print(f"ERROR: {test_file} failed with return code {test_res.returncode}")
            print(test_res.stderr)
            failed = True
        else:
            print(f"SUCCESS: {test_file} passed")
            
    if failed:
        print("\n[FAILED] Some tests failed.")
        sys.exit(1)
    else:
        print("\n[SUCCESS] All tests passed successfully!")

if __name__ == "__main__":
    main()
