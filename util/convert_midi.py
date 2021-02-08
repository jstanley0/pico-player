# this needs to match the value in firmware/sound.py
CLOCK_FREQ = 2_000_000

from argparse import ArgumentParser
from mido import MidiFile
import math

parser = ArgumentParser(description='Convert MIDI file for pico_player')
parser.add_argument('filename', type=str)
parser.add_argument('--omit-channels', type=int, metavar='CHANNEL', nargs='*')
args = parser.parse_args()
omit_channels = set(args.omit_channels)

# note on: C = channel; V = voice; D = dynamic; F = freq
# 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
#  0 C0 V1 V0 D1 D0 F9 F8 F7 F6 F5 F4 F3 F2 F1 F0

# note off: C = channel; V = voice
#  7  6  5  4  3  2  1  0
#  1  0  x  x  x C0 V1 V0 

# delay: D = delay in milliseconds
# 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
#  1  1 DD DC DB DA D9 D8 D7 D6 D5 D4 D3 D2 D1 D0

for msg in MidiFile(args.filename):
    if not msg.is_meta:
        print(msg)
