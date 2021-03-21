from argparse import ArgumentParser
from mido import MidiFile
import re

parser = ArgumentParser(description='Convert MIDI file for pico_player')
parser.add_argument('infile', type=str, help='input midi file')
parser.add_argument('-p', '--prioritize-channels', type=int, metavar='CHANNEL', nargs='*',
                    help='give specific channels priority when filling voices')
parser.add_argument('-x', '--exclude-channels', type=int, metavar='CHANNEL', nargs='*',
                    help='exclude certain channels from the output file')
parser.add_argument('outfile', type=str, help='output binary file')
args = parser.parse_args()

class Note:
    def __init__(self, midi_note, channel, velocity=0, timestamp=0):
        self.midi_note = midi_note
        self.channel = channel
        self.velocity = velocity
        self.timestamp = timestamp

class Event:
    def __init__(self, delay, previous_timestamp):
        self.delay = delay
        self.timestamp = previous_timestamp + delay
        self.notes_on = []
        self.notes_off = []

    def merge(self, prior_note_off_event):
        if prior_note_off_event.notes_on:
            raise RuntimeError('invalid merge')
        self.delay += prior_note_off_event.delay
        self.notes_off.extend(prior_note_off_event.notes_off)

class Encoder:
    def __init__(self, all_channels, priority_channels):
        self.notes_playing = [Note(None, None)] * 6
        self.events = []
        self.priority_channels = priority_channels
        self.__assign_preferred_chip(all_channels)

    def log_delay(self, delay):
        if self.events and not self.events[-1].notes_on and not self.events[-1].notes_off:
            self.events[-1].delay += delay
        else:
            self.events.append(Event(delay, self.__previous_timestamp()))

    def log_note_on(self, note, channel, velocity):
        if channel == 10:
            return  # TODO: map percussion to noise channels
        if channel not in self.preferred_chip:
            return
        event = self.__ensure_event()
        event.notes_on.append(Note(note, channel, velocity, timestamp=event.timestamp))

    def log_note_off(self, note, channel):
        if channel not in self.preferred_chip:
            return
        event = self.__ensure_event()
        event.notes_off.append(Note(note, channel, timestamp=event.timestamp))

    def write_output(self, outfile):
        self.outfile = open(outfile, 'wb')
        pending_note_off_event = None
        for event in self.events:
            # if we have a note-off event followed by another event mere milliseconds later,
            # postpone the notes-off until the next event and consolidate delay events
            if pending_note_off_event:
                if event.delay < 0.01:
                    event.merge(pending_note_off_event)
                else:
                    self.__write_event(pending_note_off_event)
                pending_note_off_event = None

            # if this event is nothing but notes-off, see if we can merge it with the next one
            if event.notes_off and not event.notes_on:
                pending_note_off_event = event
            else:
                self.__write_event(event)

        if pending_note_off_event:
            self.__write_event(pending_note_off_event)

    def __ensure_event(self):
        if not self.events:
            self.events.append(Event(0, 0))
        return self.events[-1]

    def __previous_timestamp(self):
        if self.events:
            return self.events[-1].timestamp
        return 0

    def __assign_preferred_chip(self, all_channels):
        chip = 0
        self.preferred_chip = {}
        for ch in all_channels:
            self.preferred_chip[ch] = chip
            chip ^= 1

    def __find_lru_available_voice(self, voice_range):
        voice = None
        for v in voice_range:
            playing = self.notes_playing[v]
            if not playing.midi_note:
                if voice == None or playing.timestamp < self.notes_playing[voice].timestamp:
                    voice = v
        return voice

    def __place_note(self, note):
        try:
            chip = self.preferred_chip[note.channel]

            # find the least-recently used slot on the preferred chip
            if chip == 0:
                voice_range = range(0, 3)
            else:
                voice_range = range(5, 2, -1)
            voice = self.__find_lru_available_voice(voice_range)
            if voice:
                return voice

            # no slots are available on the preferred chip, so see if we can spill to the other side
            if chip == 0:
                voice_range = range(3, 6)
            else:
                voice_range = range(2, -1, -1)
            voice = self.__find_lru_available_voice(voice_range)
            if voice:
                return voice

            # all channels are busy: possibly preempt a playing note
            preempt_candidates = []
            for v in range(6):
                playing_note = self.notes_playing[v]
                if playing_note.channel in self.priority_channels:
                    continue    # don't preempt a note in a priority channel
                # don't preempt a note that started too recently or it'll sound bad
                if note.channel in self.priority_channels:
                    time_threshold = 0.075
                else:
                    time_threshold = 0.15
                if note.channel in priority_channels or note.timestamp - playing_note.timestamp > time_threshold:
                    playing_note.voice = v
                    preempt_candidates.append(playing_note)
            if preempt_candidates:
                doomed_note = min(preempt_candidates, key=lambda note: note.timestamp)
                return doomed_note.voice

            # the note had to be dropped :(
            return None
        except KeyError:
            # this channel is excluded
            return None

    def __write_event(self, event):
        # write delay
        self.__write_delay(event.delay)

        # figure notes off
        notes_off_mask = 0
        for note_off in event.notes_off:
            for v in range(6):
                if note_off.midi_note == self.notes_playing[v].midi_note and note_off.channel == self.notes_playing[v].channel:
                    self.notes_playing[v].midi_note = None
                    self.notes_playing[v].channel = None
                    # crucially, the timestamp is left alone here; this lets us maximize release time
                    notes_off_mask |= self.__voice_bit(v)

        # write notes on
        # this looks funny because False sorts before True, but this sorts notes in priority channels first
        notes_on = sorted(event.notes_on, key=lambda note: note.channel not in self.priority_channels)
        for note_on in notes_on:
            v = self.__place_note(note_on)
            if v != None:
                self.notes_playing[v] = note_on
                self.__write_note_on(v, note_on.midi_note, note_on.velocity)
                # no need to write a note-off for this voice if we're starting a new note here now
                notes_off_mask &= ~self.__voice_bit(v)

        # write remaining notes off, if any
        if notes_off_mask != 0:
            self.__write_notes_off(notes_off_mask)

    def __midi_velocity_to_attenuation(self, velocity):
        return 7 - int(velocity / 16)

    def __decode_voice(self, v):
        # skip the noise channels
        if v < 3:
            return v
        else:
            return v + 1

    def __voice_bit(self, v):
        return 1 << self.__decode_voice(v)

    # note on: V = voice; A = attenuation; N = note
    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
    #  0  0 V2 V1 V0 A3 A2 A1 A0 N6 N5 N4 N3 N2 N1 N0
    def __write_note_on(self, v, note, velocity):
        voice = self.__decode_voice(v)
        attenuation = self.__midi_velocity_to_attenuation(velocity)
        u16 = (voice & 7) << 11
        u16 |= (attenuation & 0xF) << 7
        u16 |= (note & 0x7F)
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

    # notes off: C = channel; V = voice mask
    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
    #  1  1  0  0  0  0  0  0 V7 V6 V5 V4 V3 V2 V1 V0
    def __write_notes_off(self, voice_mask):
        self.__write16(0xC000 | voice_mask)

    def __write16(self, u16):
        self.outfile.write(u16.to_bytes(2, byteorder='big', signed=False))


midi = MidiFile(args.infile)

# NOTE: 1 is added to channels to match user-visible channel numbers in e.g. MuseScore

# I feel like there should be a better way to enumerate channels, but whatevs...
all_channels = set()
for msg in midi:
    if msg.type == 'note_on':
        all_channels.add(msg.channel + 1)

# remove excluded channels
if args.exclude_channels:
    all_channels -= set(args.exclude_channels)

# add priority channels
if args.prioritize_channels:
    priority_channels = set(args.prioritize_channels)
else:
    priority_channels = set()
    melody_track_pattern = re.compile('melody|vocals', re.I)
    for track in midi.tracks:
        if melody_track_pattern.match(track.name):
            track_channels = set()
            for msg in track:
                if msg.type == 'note_on':
                    track_channels.add(msg.channel + 1)
            print("{file}: prioritized melody track \"{name}\" channels {channels}".format(file=args.infile,name=track.name,channels=track_channels))
            priority_channels = priority_channels.union(track_channels)
        

encoder = Encoder(all_channels, priority_channels)
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
