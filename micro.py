import machine
import rp2
from rp2 import PIO, StateMachine, asm_pio
import struct
import sys

# I2S Slave Configuration
# The Pico will act as a slave, waiting for external clock signals
# GP0: BCK (Bit Clock) - INPUT from master
# GP1: WS (Word Select / LRCLK) - INPUT from master  
# GP2: SD (Serial Data) - OUTPUT to master

BCK_PIN = 0
WS_PIN = 1
SD_PIN = 2

@asm_pio(out_init=PIO.OUT_LOW, sideset_init=PIO.OUT_LOW)
def i2s_slave_tx():
    """
    I2S slave transmitter PIO program
    Waits for external BCK and WS signals
    Transmits 32-bit samples (16-bit left + 16-bit right)
    """
    # Wait for WS low (left channel start)
    wait(0, pin, 0)  # Wait for WS low
    
    # Transmit 16 bits for left channel
    set(x, 15)
    label("left_loop")
    wait(1, pin, 1)  # Wait for BCK rising edge
    out(pins, 1)     # Output 1 bit
    wait(0, pin, 1)  # Wait for BCK falling edge
    jmp(x_dec, "left_loop")
    
    # Wait for WS high (right channel start)
    wait(1, pin, 0)  # Wait for WS high
    
    # Transmit 16 bits for right channel
    set(x, 15)
    label("right_loop")
    wait(1, pin, 1)  # Wait for BCK rising edge
    out(pins, 1)     # Output 1 bit
    wait(0, pin, 1)  # Wait for BCK falling edge
    jmp(x_dec, "right_loop")


class I2SSlaveTX:
    def __init__(self, bck_pin=BCK_PIN, ws_pin=WS_PIN, sd_pin=SD_PIN, sm_id=0):
        """Initialize I2S slave transmitter"""
        self.bck_pin = machine.Pin(bck_pin, machine.Pin.IN)
        self.ws_pin = machine.Pin(ws_pin, machine.Pin.IN)
        self.sd_pin = machine.Pin(sd_pin, machine.Pin.OUT)
        
        # Initialize PIO state machine
        self.sm = StateMachine(
            sm_id,
            i2s_slave_tx,
            freq=125_000_000,  # Max PIO clock for responsiveness
            out_base=self.sd_pin,
            in_base=self.bck_pin,
            jmp_pin=self.ws_pin,
            out_shiftdir=PIO.SHIFT_LEFT,
        )
        
        self.sm.active(1)
        print("I2S Slave TX initialized")
        print(f"  BCK (input): GP{bck_pin}")
        print(f"  WS (input): GP{ws_pin}")
        print(f"  SD (output): GP{sd_pin}")
    
    def send_sample(self, left, right):
        """
        Send a single stereo sample (16-bit left, 16-bit right)
        Blocks until the sample is transmitted
        """
        # Pack as 32-bit value: left channel in upper 16 bits, right in lower 16 bits
        sample = ((left & 0xFFFF) << 16) | (right & 0xFFFF)
        self.sm.put(sample)
    
    def send_samples(self, samples):
        """
        Send multiple samples from a buffer
        samples: list of (left, right) tuples or bytes buffer
        """
        if isinstance(samples, (bytes, bytearray)):
            # Parse as 16-bit stereo samples
            for i in range(0, len(samples), 4):
                if i + 3 < len(samples):
                    left = struct.unpack('<h', samples[i:i+2])[0]
                    right = struct.unpack('<h', samples[i+2:i+4])[0]
                    self.send_sample(left, right)
        else:
            for left, right in samples:
                self.send_sample(left, right)


def parse_wav_header(header):
    """Parse WAV file header and return format info"""
    if header[0:4] != b'RIFF' or header[8:12] != b'WAVE':
        raise ValueError("Not a valid WAV file")
    
    # Find fmt chunk
    pos = 12
    while pos < len(header) - 8:
        chunk_id = header[pos:pos+4]
        chunk_size = struct.unpack('<I', header[pos+4:pos+8])[0]
        
        if chunk_id == b'fmt ':
            fmt_data = header[pos+8:pos+8+chunk_size]
            audio_format = struct.unpack('<H', fmt_data[0:2])[0]
            channels = struct.unpack('<H', fmt_data[2:4])[0]
            sample_rate = struct.unpack('<I', fmt_data[4:8])[0]
            bits_per_sample = struct.unpack('<H', fmt_data[14:16])[0]
            
            return {
                'format': audio_format,
                'channels': channels,
                'sample_rate': sample_rate,
                'bits': bits_per_sample
            }
        
        pos += 8 + chunk_size
    
    raise ValueError("No fmt chunk found")


def stream_audio():
    """Main streaming function - receives audio data from USB serial"""
    i2s = I2SSlaveTX()
    
    print("\nReady to receive audio data")
    print("Waiting for WAV header...")
    
    # Read WAV header (first 44 bytes minimum)
    header = sys.stdin.buffer.read(44)
    
    if len(header) < 44:
        print("Error: Incomplete header")
        return
    
    try:
        info = parse_wav_header(header)
        print(f"\nWAV Format:")
        print(f"  Sample Rate: {info['sample_rate']} Hz")
        print(f"  Channels: {info['channels']}")
        print(f"  Bits: {info['bits']}")
        
        if info['bits'] != 16 or info['channels'] != 2:
            print("Warning: Only 16-bit stereo supported, conversion may be needed")
        
        # Find data chunk
        pos = 12
        data_start = None
        while pos < len(header) - 8:
            chunk_id = header[pos:pos+4]
            chunk_size = struct.unpack('<I', header[pos+4:pos+8])[0]
            if chunk_id == b'data':
                data_start = pos + 8
                break
            pos += 8 + chunk_size
        
        # Read remaining header if data chunk not found yet
        if data_start is None:
            extra = sys.stdin.buffer.read(100)
            header += extra
        
        print("\nStreaming audio...")
        
        # Stream audio data in chunks
        chunk_size = 512  # Process 512 bytes at a time (128 stereo samples)
        while True:
            data = sys.stdin.buffer.read(chunk_size)
            if not data:
                break
            
            i2s.send_samples(data)
        
        print("\nStreaming complete")
        
    except ValueError as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    print("=== Raspberry Pi Pico I2S Slave Transmitter ===")
    print("Connect I2S master device:")
    print("  Master BCK -> Pico GP0")
    print("  Master WS  -> Pico GP1")
    print("  Pico GP2   -> Master SD")
    print("=" * 48)
    
    stream_audio()
