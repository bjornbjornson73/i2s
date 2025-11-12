#!/usr/bin/env python3
"""
PC-side WAV file sender for Raspberry Pi Pico I2S slave transmitter
Sends WAV file data over USB serial to the Pico
"""

import serial
import serial.tools.list_ports
import sys
import time
import wave
import struct


def find_pico_port():
    """Automatically find the Raspberry Pi Pico serial port"""
    ports = serial.tools.list_ports.comports()
    
    for port in ports:
        # Look for Pico identifiers
        if 'USB Serial' in port.description or 'Pico' in port.description:
            return port.device
        # On some systems, check VID/PID for Raspberry Pi
        if port.vid == 0x2E8A:  # Raspberry Pi vendor ID
            return port.device
    
    return None


def convert_to_stereo_16bit(wav_file):
    """
    Convert WAV file to 16-bit stereo format if needed
    Returns converted audio data as bytes
    """
    with wave.open(wav_file, 'rb') as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        
        print(f"Input WAV: {framerate}Hz, {channels}ch, {sampwidth*8}-bit")
        
        # Convert to 16-bit if needed
        if sampwidth == 1:  # 8-bit
            samples = list(frames)
            # Convert 8-bit unsigned to 16-bit signed
            samples_16 = [(s - 128) * 256 for s in samples]
            frames = struct.pack(f'<{len(samples_16)}h', *samples_16)
        elif sampwidth == 3:  # 24-bit
            samples_24 = [int.from_bytes(frames[i:i+3], 'little', signed=True) 
                          for i in range(0, len(frames), 3)]
            # Convert to 16-bit by dividing by 256
            samples_16 = [s // 256 for s in samples_24]
            frames = struct.pack(f'<{len(samples_16)}h', *samples_16)
        elif sampwidth == 4:  # 32-bit
            samples_32 = struct.unpack(f'<{len(frames)//4}i', frames)
            # Convert to 16-bit by dividing by 65536
            samples_16 = [s // 65536 for s in samples_32]
            frames = struct.pack(f'<{len(samples_16)}h', *samples_16)
        
        # Convert mono to stereo if needed
        if channels == 1:
            samples = struct.unpack(f'<{len(frames)//2}h', frames)
            # Duplicate each sample for both channels
            stereo_samples = []
            for s in samples:
                stereo_samples.extend([s, s])
            frames = struct.pack(f'<{len(stereo_samples)}h', *stereo_samples)
            channels = 2
        
        # Create new WAV header for 16-bit stereo
        output = bytearray()
        
        # RIFF header
        output.extend(b'RIFF')
        output.extend(struct.pack('<I', 36 + len(frames)))
        output.extend(b'WAVE')
        
        # fmt chunk
        output.extend(b'fmt ')
        output.extend(struct.pack('<I', 16))  # Chunk size
        output.extend(struct.pack('<H', 1))   # Audio format (PCM)
        output.extend(struct.pack('<H', channels))
        output.extend(struct.pack('<I', framerate))
        output.extend(struct.pack('<I', framerate * channels * 2))  # Byte rate
        output.extend(struct.pack('<H', channels * 2))  # Block align
        output.extend(struct.pack('<H', 16))  # Bits per sample
        
        # data chunk
        output.extend(b'data')
        output.extend(struct.pack('<I', len(frames)))
        output.extend(frames)
        
        print(f"Converted to: {framerate}Hz, 2ch, 16-bit")
        return bytes(output)


def send_wav_file(port, wav_file, chunk_size=512):
    """Send WAV file to Pico over serial"""
    
    print(f"Opening serial port: {port}")
    try:
        ser = serial.Serial(port, 115200, timeout=1)
        time.sleep(2)  # Wait for Pico to reset and initialize
        
        # Read any initialization messages from Pico
        while ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore')
            print(f"Pico: {line.strip()}")
        
        print(f"\nConverting and sending: {wav_file}")
        
        # Convert WAV to proper format
        wav_data = convert_to_stereo_16bit(wav_file)
        
        total_size = len(wav_data)
        sent = 0
        
        print(f"Total size: {total_size} bytes ({total_size / (1024*1024):.2f} MB)")
        print("\nSending...")
        
        start_time = time.time()
        
        # Send in chunks
        for i in range(0, len(wav_data), chunk_size):
            chunk = wav_data[i:i+chunk_size]
            ser.write(chunk)
            sent += len(chunk)
            
            # Progress indicator
            percent = (sent / total_size) * 100
            if sent % (chunk_size * 10) == 0:  # Update every 10 chunks
                elapsed = time.time() - start_time
                speed = sent / elapsed / 1024  # KB/s
                print(f"\rProgress: {percent:.1f}% ({sent}/{total_size} bytes) - {speed:.1f} KB/s", 
                      end='', flush=True)
        
        print("\n\nTransmission complete!")
        
        elapsed = time.time() - start_time
        print(f"Time: {elapsed:.2f}s")
        print(f"Average speed: {sent / elapsed / 1024:.1f} KB/s")
        
        # Read any final messages
        time.sleep(0.5)
        while ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore')
            print(f"Pico: {line.strip()}")
        
        ser.close()
        
    except serial.SerialException as e:
        print(f"Serial error: {e}")
        return False
    except FileNotFoundError:
        print(f"File not found: {wav_file}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False
    
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python pc_wav_sender.py <wav_file> [serial_port]")
        print("\nExample:")
        print("  python pc_wav_sender.py audio.wav")
        print("  python pc_wav_sender.py audio.wav /dev/ttyACM0")
        print("  python pc_wav_sender.py audio.wav COM3")
        sys.exit(1)
    
    wav_file = sys.argv[1]
    
    # Find or use specified port
    if len(sys.argv) >= 3:
        port = sys.argv[2]
    else:
        print("Searching for Raspberry Pi Pico...")
        port = find_pico_port()
        
        if not port:
            print("Could not find Pico. Available ports:")
            for p in serial.tools.list_ports.comports():
                print(f"  {p.device}: {p.description}")
            print("\nPlease specify port manually:")
            print("  python pc_wav_sender.py <wav_file> <port>")
            sys.exit(1)
        
        print(f"Found Pico on: {port}")
    
    # Send the file
    send_wav_file(port, wav_file)


if __name__ == "__main__":
    main()
