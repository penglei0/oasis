#!/usr/bin/env sh
# Wrapper of `sudo python3 oasis_src/src/start.py ...`
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Usage:
# 
# ./tools/run_test.sh protocol-ci-test.yaml:test1
# Optional args:  --cleanup     # to clean up previous test results
#                 --skip-copy   # to skip copying the binary files to oasis rootfs
#
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
has_root_privilege="sudo "
current_path=$(pwd)
oasis_help_scripts="<==== Oasis Helper scripts ===> "
oasis_check_passed_mark=' [✓]'
oasis_check_failed_mark=' [✗]'
print_message() {
    local message="$1"
    local status="$2"  # "pass" or "fail"
    if [ "$status" = "fail" ]; then
        echo "$oasis_help_scripts""$message""$oasis_check_failed_mark"
    elif [ "$status" = "pass" ]; then
        echo "$oasis_help_scripts""$message""$oasis_check_passed_mark"
    else
        echo "$oasis_help_scripts""$message"
    fi
}

delete_flag_files() {
    if [ -f "$current_path"/oasis_src/test.failed ]; then
        ${has_root_privilege}rm "$current_path"/oasis_src/test.failed
    fi

    if [ -f "$current_path"/oasis_src/test.success ]; then
        ${has_root_privilege}rm "$current_path"/oasis_src/test.success
    fi
}

if [ ! -d .git ]; then
    print_message "This script should be run in the root directory of the your Git repository." fail
    exit 1
fi
print_message "Current path is $current_path" pass

repo_url=$(git config --get remote.origin.url)
repo_name=$(basename "$repo_url" .git)
print_message "Current git repo URL is $repo_url" pass
print_message "Current git repo name is $repo_name" pass

if [ ! -d oasis_src ]; then
    print_message "Oasis_src directory not found. Cloning submodule..."
    git submodule update --init
fi
print_message "Found Oasis's source code" pass

test_yaml_file=$1
shift
other_args_for_oasis="$*"

cleanup_flag="\-\-cleanup"
skip_copy_flag="\-\-skip-copy"
privilege_flags="\-\-no-privilege"

has_confirmed_cleanup=""
has_skipped_copy=""

if [ -n "$other_args_for_oasis" ]; then
    if echo "$other_args_for_oasis" | grep -q "$cleanup_flag"; then
        print_message "Will do the cleanup of previous test results without confirmation." pass
        other_args_for_oasis=$(echo "$other_args_for_oasis" | sed "s/--cleanup//g")
        has_confirmed_cleanup="True"
    fi    
    if echo "$other_args_for_oasis" | grep -q "$skip_copy_flag"; then
        print_message "Will skip copying the binary files to oasis rootfs." pass
        other_args_for_oasis=$(echo "$other_args_for_oasis" | sed "s/--skip-copy//g")
        has_skipped_copy="True"
    fi
    
    if echo "$other_args_for_oasis" | grep -q "$privilege_flags"; then
        other_args_for_oasis=$(echo "$other_args_for_oasis" | sed "s/--no-privilege//g")
        has_root_privilege=""
        print_message "Run the test without root privilege."
    else
        has_root_privilege="sudo "
        print_message "Run the test with root privilege."
    fi
    # Trim extra spaces from cleaned arguments
    other_args_for_oasis=$(echo "$other_args_for_oasis" | xargs)
fi

# Step 1: copy files to rootfs
if [ "$has_skipped_copy" != "True" ]; then
    # TODO(.): define the files to copy
    files_to_copy="./build/bin/your_binary_files"
    for file in $files_to_copy; do
        if [ -f "$file" ]; then
            print_message "Found $file and update it to oasis rootfs" pass
            cp "$file" test/rootfs/usr/bin/
        else
            print_message "File $file not found, skipping update..."
        fi
    done
fi

if [ -z "$test_yaml_file" ]; then
    print_message "Invalid input args" fail
    print_message "Usage: $0 <test_yaml_file> [optional args pass to oasis]"
    print_message "Example: $0 protocol-ci-test.yaml:test1"
    print_message "Optional args: --cleanup      # to clean up previous test results"
    print_message "               --skip-copy    # to skip copying the binary files to oasis rootfs"
    print_message "               --no-privilege # to run the test without sudo"
    exit 1
fi

IFS=':' read -r test_yaml_file_name test_name <<EOF
$test_yaml_file
EOF
print_message "Test YAML file: $test_yaml_file_name, Test name: $test_name" pass

if [ ! -f "$current_path""/test/""$test_yaml_file_name" ]; then
    print_message "Test YAML file: $test_yaml_file_name not found in $current_path/test/ directory." fail
    print_message "Please provide a valid test YAML file."
    exit 1
fi

# Step 2: run test
print_message "Running test with args: $other_args_for_oasis" pass
if [ -n "$test_name" ]; then
    test_result_dir="$current_path""/oasis_src/test_results/""$test_name"
    if [ -d "$test_result_dir" ] && [ "$has_confirmed_cleanup" = "" ]; then
        printf "%sDo you want to clean up previous test results under %s? (Y/n): " "$oasis_help_scripts" "$test_result_dir"
        read -r confirm
        if [ "$confirm" = "Y" ] || [ "$confirm" = "y" ] || [ -z "$confirm" ]; then
            has_confirmed_cleanup="True"
        fi
    fi

    if [ -d "$test_result_dir" ] && [ "$has_confirmed_cleanup" = "True" ]; then
        ${has_root_privilege}rm -rf "$test_result_dir"
        print_message "Cleaned up previous test results."
    else
        print_message "Skipping cleanup of previous test results.($test_name)"
    fi
fi

delete_flag_files

exe_cmd=$has_root_privilege"python3 oasis_src/src/start.py -p test --containernet=default -t ${test_yaml_file} ${other_args_for_oasis}"
print_message "Oasis test with command: $exe_cmd" pass
# Run the test
$exe_cmd
test_result_dir="$current_path""/oasis_src/test_results/""$test_name"


print_message "#####################################################################"
if [ -f "${current_path}/oasis_src/test.failed" ] || [ ! -f "${current_path}/oasis_src/test.success" ]; then
    print_message "Oasis test failed on ""$test_yaml_file" fail
    exit 1
else
    print_message "Oasis test success" pass
    print_message "Oasis test results were saved to ""$current_path""/oasis_src/test_results/""$test_name"
fi
print_message "#####################################################################"

delete_flag_files

# TODO(.): do some processing of test results
# e.g., extract data from log files, generate index.html, etc.
if [ -f oasis_src/src/tools/extract_data.py ]; then
    ${has_root_privilege}python3 -u oasis_src/src/tools/extract_data.py "$test_result_dir"
fi

if [ -f oasis_src/src/tools/generate_index.py ]; then
    ${has_root_privilege}python3 -u oasis_src/src/tools/generate_index.py "$test_result_dir"
fi

exit 0
