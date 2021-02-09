# this needs to match the value in firmware/sound.py
CLOCK_FREQ = 2_000_000

from argparse import ArgumentParser
from mido import MidiFile
import math

parser = ArgumentParser(description='Convert MIDI file for pico_player')
parser.add_argument('infile', type=str, help='input midi file')
parser.add_argument('-p', '--channel-priority', type=int, metavar='CHANNEL', nargs='*',
                    help='process (1-based) channels in the given order, excluding entirely if not given')
parser.add_argument('outfile', type=str, help='output binary file')
args = parser.parse_args()

class Event:
    def __init__(self, delay=0):
        self._delay = delay
        self._notes_on = []
        self._notes_off = []

    def delay(self):
        return self._delay

    def add_delay(self, t):
        self._delay += t
        return self._delay

    def add_note_on(self, note):
        self._notes_on.append(note)

    def add_note_off(self, note):
        self._notes_off.append(note)

    def notes_on(self):
        return self._notes_on

    def notes_off(self):
        return self._notes_off


class Encoder:
    def __init__(self, outfile, all_channels, channel_priority):
        self.preferred_index = __compute_preferred_index(all_channels, channel_priority)
        self.notes_playing = [None, None, None, None, None, None]
        self.events = []
        self.outfile = outfile

    def log_delay(self, delay):
        if self.events and not self.events[-1].notes_on() and not self.events[-1].notes_off():
            self.events[-1].add_delay(delay)
        else:
            self.__write_last_event()
            self.events.append(Event(delay))

    def log_note_on(self, note, channel, velocity):
        self.__ensure_event()
        self.events[-1].add_note_on((note, channel, velocity))

    def log_note_off(self, note, channel):
        self.__ensure_event()
        self.events[-1].add_note_off((note, channel))

    def finish(self):
        self.__write_last_event()

    def __ensure_event(self):
        if not self.events:
            self.events.append(Event(0))

    def __compute_preferred_index(all_channels, channel_priority):
        if channel_priority:
            pass
        else:
            pass

    def __place_note(self, note):
        try:
            i = self.preferred_index[note[1]]
            if self.notes_playing[i] == None:
                # easy: our preferred voice is available
                return i
            elif i < 3:
                # try to find a voice on the left channel
                # but prefer spilling to the right to dropping entirely
                for j in range(6):
                    if self.notes_playing[j] == None:
                        return j
            else:
                # try to find a voice on the right channel
                for j in range(5,-1,-1):
                    if self.notes_playing[j] == None:
                        return j
            return None

        except KeyError:
            # this channel is excluded
            pass

    def __write_last_event(self):
        if not self.events:
            return
        event = self.events[-1]

        # sanity check
        print('writing event:')
        print(delay)
        print(event.notes_off)
        print(event.notes_on)
        print('---')

        # write delay
        self.__write_delay(self.delay)

        # write notes off
        for note_off in event.notes_off():
            try:
                i = self.notes_playing.index(note_off)
                self.notes_playing[i] = None
                self.__write_note_off(i)
            except ValueError:
                # we probably had to drop this note earlier
                # or maybe we're ignoring this channel entirely
                pass

        # write notes on
        # FIXME sort by channel priority somehow!
        for note_on in event.notes_on():
            i = self.__place_note(note_on)
            if i != None
                self.notes_playing[i] = (note_on[0], note_on[1])
                self.__write_note_on(i, note_on[0], note_on[2]

    def __midi_note_to_frequency(self, midi_note):
        return int(round(CLOCK_FREQ / (32 * 440.0 * math.pow(2, (midi_note - 69.0) / 12))))

    def __midi_velocity_to_dynamic(self, velocity):
        return int(velocity / 32)

    def __decode_index(self, index):
        if index < 3:
            return (0, index)
        else:
            return (1, index - 3)

    # delay: D = delay in milliseconds
    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
    #  1  1 DD DC DB DA D9 D8 D7 D6 D5 D4 D3 D2 D1 D0
    def __write_delay(self, delay):
        while delay > 0x3FFF:
            __write16(0xFFFF)
            delay -= 0x3FFF
        if delay > 0:
            __write16(0xC000 | delay)

    # note on: C = channel; V = voice; D = dynamic; F = freq
    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
    #  0 C0 V1 V0 D1 D0 F9 F8 F7 F6 F5 F4 F3 F2 F1 F0
    def __write_note_on(self, index, note, velocity):
        channel, voice = self.__decode_index(index)
        frequency = self.__midi_note_to_frequency(note)
        dynamic = self.__midi_velocity_to_dynamic(velocity)
        u16 = (channel & 1) << 14
        u16 |= (voice & 3) << 12
        u16 |= (dynamic & 3) << 10
        u16 |= (frequency & 0x3FF)
        __write16(u16)

    # note off: C = channel; V = voice
    #  7  6  5  4  3  2  1  0
    #  1  0  x  x  x C0 V1 V0
    def __write_note_off(self, index):
        channel, voice = self.__decode_index(index)
        u8 = 0x80
        u8 |= (channel & 1) << 2
        u8 |= (voice & 3)
        __write8(u8)

    def __write16(self, u16):
        self.outfile.write(u16.to_bytes(2, byteorder='big', signed=False)

    def __write8(self, u8):
        self.outfile.write(u8.to_bytes(1, byteorder='big', signed=False)


midi = MidiFile(args.infile)

# I feel like there should be a better way to enumerate channels, but whatevs...
all_channels = set()
for msg in midi:
    all_channels.add(msg.channel)

encoder = Encoder(args.outfile, all_channels, args.channel_priority)
for msg in midi:
    if msg.time > 0:
        encoder.log_delay(msg.time)
    if not msg.is_meta:
        if msg.type == 'note_on':
            if msg.velocity == 0:
                encoder.log_note_off(msg.note, msg.channel + 1)
            else:
                encoder.log_note_on(msg.note, msg.channel + 1, msg.velocity)
        elif msg.type == 'note_off':
            encoder.log_note_off(msg.note, msg.channel + 1)
encoder.finish()
