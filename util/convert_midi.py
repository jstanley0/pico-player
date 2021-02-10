# this needs to match the value in firmware/sound.py
CLOCK_FREQ = 1_200_000

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

    def merge(self, note_off_event):
        if note_off_event.notes_on():
            raise RuntimeError('invalid merge')
        self.add_delay(note_off_event.delay())
        self._notes_off.extend(note_off_event.notes_off())

class Encoder:
    def __init__(self, channel_priority):
        self.notes_playing = [None] * 6
        self.events = []
        self.__compute_channel_sort_keys(channel_priority)
        self.__compute_preferred_voice(channel_priority)

    def log_delay(self, delay):
        if self.events and not self.events[-1].notes_on() and not self.events[-1].notes_off():
            self.events[-1].add_delay(delay)
        else:
            self.events.append(Event(delay))

    def log_note_on(self, note, channel, velocity):
        if channel == 10:
            return  # TODO: map percussion to noise channels
        self.__ensure_event()
        self.events[-1].add_note_on((note, channel, velocity))

    def log_note_off(self, note, channel):
        self.__ensure_event()
        self.events[-1].add_note_off((note, channel))

    def write_output(self, outfile):
        self.outfile = open(outfile, 'wb')
        pending_note_off_event = None
        for event in self.events:
            # if we have a note-off event followed by another event mere milliseconds later,
            # postpone the notes-off until the next event and consolidate delay events
            if pending_note_off_event:
                if event.delay() < 0.01:
                    event.merge(pending_note_off_event)
                else:
                    self.__write_event(pending_note_off_event)
                pending_note_off_event = None

            # if this event is nothing but notes-off, see if we can merge it with the next one
            if event.notes_off() and not event.notes_on():
                pending_note_off_event = event
            else:
                self.__write_event(event)

        if pending_note_off_event:
            self.__write_event(pending_note_off_event)

    def __ensure_event(self):
        if not self.events:
            self.events.append(Event(0))

    def __compute_preferred_voice(self, channel_priority):
        order = [0, 5, 1, 4, 2, 3]
        ix = 0
        self.preferred_voice = {}
        for ch in channel_priority:
            self.preferred_voice[ch] = order[ix]
            ix = (ix + 1) % len(order)
        print('preferred_voice')
        print(self.preferred_voice)

    def __compute_channel_sort_keys(self, channel_priority):
        key = 0
        self.channel_sort_keys = {}
        for ch in channel_priority:
            self.channel_sort_keys[ch] = key
            key += 1
        print('channel_sort_keys')
        print(self.channel_sort_keys)

    def __place_note(self, note):
        try:
            v = self.preferred_voice[note[1]]
            if self.notes_playing[v] == None:
                # easy: our preferred voice is available
                return v
            elif v < 3:
                # try to find a voice on the left channel
                # but prefer spilling to the right to dropping entirely
                for w in range(6):
                    if self.notes_playing[w] == None:
                        return w
            else:
                # try to find a voice on the right channel
                for w in range(5,-1,-1):
                    if self.notes_playing[w] == None:
                        return w
            # TODO: maybe: pick a lower-priority voice to interrupt/preempt
            return None
        except KeyError:
            # this channel is excluded
            return None

    def __write_event(self, event):
        # sanity check
        print('write_event:')
        print(event.delay())
        print(event.notes_off())
        print(event.notes_on())

        # write delay
        self.__write_delay(event.delay())

        # figure notes off
        notes_off = 0
        for note_off in event.notes_off():
            try:
                v = self.notes_playing.index(note_off)
                self.notes_playing[v] = None
                notes_off |= self.__voice_bit(v)
            except ValueError:
                # we probably had to drop this note earlier
                # or maybe we're ignoring this channel entirely
                pass

        # write notes on
        filtered_notes_on = filter(lambda note: note[1] in self.channel_sort_keys, event.notes_on())
        notes_on = sorted(filtered_notes_on, key=lambda note: self.channel_sort_keys[note[1]])
        for note_on in notes_on:
            v = self.__place_note(note_on)
            if v != None:
                self.notes_playing[v] = (note_on[0], note_on[1])
                self.__write_note_on(v, note_on[0], note_on[2])
                # no need to write a note-off for this voice if we're starting a new note here now
                notes_off &= ~self.__voice_bit(v)

        # write remaining notes off, if any
        if notes_off != 0:
            self.__write_notes_off(notes_off)

        print('notes_playing:')
        print(self.notes_playing)
        print('---')

    # shift notes up an octave if they would otherwise overflow the frequency register
    def __remap_note_if_necessary(self, note):
        while self.__midi_note_to_frequency(note) >= 1024:
            note += 12
        return note

    def __midi_note_to_frequency(self, midi_note):
        return round(CLOCK_FREQ / (32 * 440.0 * math.pow(2, (midi_note - 69.0) / 12)))

    def __midi_velocity_to_dynamic(self, velocity):
        return int(velocity / 32)

    def __decode_voice(self, v):
        if v < 3:
            return (0, v)
        else:
            return (1, v - 3)

    def __voice_bit(self, v):
        if v < 4:
            return 1 << v
        else:
            return 0x10 << (v - 3)

    # note on: C = channel; V = voice; D = dynamic; F = freq
    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
    #  0 C0 V1 V0 D1 D0 F9 F8 F7 F6 F5 F4 F3 F2 F1 F0
    def __write_note_on(self, v, note, velocity):
        channel, voice = self.__decode_voice(v)
        note = self.__remap_note_if_necessary(note)
        frequency = self.__midi_note_to_frequency(note)
        dynamic = self.__midi_velocity_to_dynamic(velocity)
        u16 = (channel & 1) << 14
        u16 |= (voice & 3) << 12
        u16 |= (dynamic & 3) << 10
        u16 |= (frequency & 0x3FF)
        self.__write16(u16)

    # delay: D = delay in milliseconds
    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
    #  1  0 DD DC DB DA D9 D8 D7 D6 D5 D4 D3 D2 D1 D0
    def __write_delay(self, delay):
        delay = round(delay * 1000)
        while delay > 0x3FFF:
            self.__write16(0xBFFF)
            delay -= 0x3FFF
        if delay > 0:
            self.__write16(0x8000 | delay)

    # notes off: C = channel; L = left chip; R = right chip
    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
    #  1  1  0  0  0  0  0  0 R3 R2 R1 R0 L3 L2 L1 L0
    def __write_notes_off(self, voice_mask):
        self.__write16(0xC000 | voice_mask)

    def __write16(self, u16):
        self.outfile.write(u16.to_bytes(2, byteorder='big', signed=False))


midi = MidiFile(args.infile)

# NOTE: 1 is added to channels to match user-visible channel numbers in e.g. MuseScore

# I feel like there should be a better way to enumerate channels, but whatevs...
channel_priority = args.channel_priority
if not channel_priority:
    channel_priority = set()
    for msg in midi:
        if msg.type == 'note_on':
            channel_priority.add(msg.channel + 1)

encoder = Encoder(channel_priority)
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
encoder.write_output(args.outfile)
