#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    plugins.__init__.py

    Written by:               Josh.5 <jsunnex@gmail.com>
    Modified by:              Nirin. 
    Date:                     30 Sep 2021, (03:45 PM)

    Copyright:
        Copyright (C) 2021 Josh Sunnex

        This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
        Public License as published by the Free Software Foundation, version 3.

        This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the
        implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
        for more details.

        You should have received a copy of the GNU General Public License along with this program.
        If not, see <https://www.gnu.org/licenses/>.

"""

import logging

from unmanic.libs.unplugins.settings import PluginSettings
from convert_multichan_audio_to_stereo.lib.ffmpeg import Probe, Parser

# Configure plugin logger
logger = logging.getLogger("Unmanic.Plugin.convert_multichan_audio_to_stereo")


def has_stereo_track(probe_streams):
    """Return True if any existing stereo audio track is present (excluding commentary tracks)."""
    for s in probe_streams:
        if s['codec_type'] != 'audio' or s.get('channels', 0) != 2:
            continue
        title = s.get('tags', {}).get('title', '')
        if 'commentary' not in title.lower():
            return True
    return False


class Settings(PluginSettings):
    settings = {
        "use_libfdk_aac":            True,
        "encode_all_2_aac":          True,
        "keep_mc":                   True,
        "set_2ch_stream_as_default": False,
        "normalize_2_channel_stream": True,
        'I':                         '-16.0',
        'LRA':                       '11.0',
        'TP':                        '-1.5',
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)
        self.form_settings = {
            "use_libfdk_aac": {
                "label": "check if you want to use libfdk_aac (requires ffmpeg >= 5), otherwise native aac is used",
            },
            "encode_all_2_aac": {
                "label": "check this if you want to re-encode all existing, non-aac, streams to aac using selected encoder - otherwise all other streams left as is",
            },
            "keep_mc": {
                "label": "uncheck to delete the multichannel streams after they are remixed to stereo",
            },
            "set_2ch_stream_as_default": {
                "label": "check to set the default audio stream as the new 2 channel stream.",
            },
            "normalize_2_channel_stream": {
                "label": "check this to normalize the resulting 2 channel audio stream - customizeable settings will appear below when checked",
            },
            "I": self.__set_I_form_settings(),
            "LRA": self.__set_LRA_form_settings(),
            "TP": self.__set_TP_form_settings(),
        }

    def __set_I_form_settings(self):
        values = {
            "label": "Integrated loudness target",
            "input_type": "slider",
            "slider_options": {
                "min": -70.0,
                "max": -5.0,
                "step": 0.1,
            },
        }
        if not self.get_setting('normalize_2_channel_stream'):
            values["display"] = 'hidden'
        return values

    def __set_LRA_form_settings(self):
        values = {
            "label": "Loudness range",
            "input_type": "slider",
            "slider_options": {
                "min": 1.0,
                "max": 20.0,
                "step": 0.1,
            },
        }
        if not self.get_setting('normalize_2_channel_stream'):
            values["display"] = 'hidden'
        return values

    def __set_TP_form_settings(self):
        values = {
            "label": "The maximum true peak",
            "input_type": "slider",
            "slider_options": {
                "min": -9.0,
                "max": 0,
                "step": 0.1,
            },
        }
        if not self.get_setting('normalize_2_channel_stream'):
            values["display"] = 'hidden'
        return values


def streams_to_stereo_encode(probe_streams):
    stereo_streams = [
        s['tags']['language']
        for s in probe_streams
        if s['codec_type'] == 'audio'
        and 'tags' in s and 'language' in s['tags']
        and s['channels'] == 2
        and (("title" not in s['tags']) or ("commentary" not in s['tags'].get("title", "").lower()))
    ]

    streams = []
    for s in probe_streams:
        if s['codec_type'] == 'audio' and s.get('channels', 0) > 2:
            if 'tags' in s and 'language' in s['tags'] and s['tags']['language'] not in stereo_streams:
                streams.append(s['index'])  # absolute input index

    return streams


def on_library_management_file_test(data):
    abspath = data.get('path')
    probe_data = Probe(logger, allowed_mimetypes=['audio', 'video'])

    if probe_data.file(abspath):
        probe_streams = probe_data.get_probe()["streams"]
    else:
        logger.debug("Probe data failed - Blocking everything.")
        data['add_file_to_pending_tasks'] = False
        return data

    settings = Settings(library_id=data.get('library_id')) if data.get('library_id') else Settings()

    stereo_exists = has_stereo_track(probe_streams)
    encode_all_2_aac = settings.get_setting('encode_all_2_aac')

    non_aac_exists = any(
        s['codec_type'] == 'audio' and s['codec_name'] != 'aac'
        for s in probe_streams
    )
    mc_exists = any(
        s['codec_type'] == 'audio' and s.get('channels', 0) > 2
        for s in probe_streams
    )

    if (not stereo_exists and mc_exists) or (encode_all_2_aac and non_aac_exists):
        data['add_file_to_pending_tasks'] = True
    else:
        logger.debug(f"do not add file '{abspath}' to task list - no relevant audio streams")

    return data


def audio_filtergraph(settings):
    i = settings.get_setting('I')
    lra = settings.get_setting('LRA')
    tp = settings.get_setting('TP')
    return f'loudnorm=I={i}:LRA={lra}:TP={tp}'


def on_worker_process(data):
    data['exec_command'] = []
    data['repeat'] = False

    abspath = data.get('file_in')
    outpath = data.get('file_out')

    probe_data = Probe(logger, allowed_mimetypes=['audio', 'video'])
    if not probe_data.file(abspath):
        logger.debug(f"Probe data failed - Nothing to encode - '{abspath}'")
        return data

    probe_streams = probe_data.get_probe()["streams"]

    # Settings
    settings = Settings(library_id=data.get('library_id')) if data.get('library_id') else Settings()
    keep_mc = settings.get_setting('keep_mc')
    defaudio2ch = settings.get_setting('set_2ch_stream_as_default')
    encode_all_2_aac = settings.get_setting('encode_all_2_aac')
    normalize_2_channel_stream = settings.get_setting('normalize_2_channel_stream')
    encoder = 'libfdk_aac' if settings.get_setting('use_libfdk_aac') else 'aac'

    stereo_exists = has_stereo_track(probe_streams)

    all_astreams = [s['index'] for s in probe_streams if s['codec_type'] == 'audio']

    if not all_astreams:
        logger.debug(f"do not add file '{abspath}' to task list - no audio streams")
        return data

    # Preserve dispositions
    existing_dispositions = {s['index']: s.get('disposition', {}).copy() for s in probe_streams}

    ffmpeg_args = [
        '-hide_banner', '-loglevel', 'info', '-i', str(abspath),
        '-max_muxing_queue_size', '9999',
        '-map', '0:v', '-c:v', 'copy'
    ]

    next_audio_stream_index = 0

    for abs_stream in all_astreams:
        s = probe_streams[abs_stream]
        chnls = s.get('channels', 0)

        # Decide if we need to re-encode this stream in place
        must_reencode = encode_all_2_aac and s['codec_type'] == 'audio' and s['codec_name'] != 'aac'

        ffmpeg_args += ['-map', f'0:{abs_stream}']

        if must_reencode:
            rate = '128k'
            if 'bit_rate' in s:
                rate = str(int(int(s['bit_rate']) / (1000 * max(chnls, 1))) * 2) + 'k'

            ffmpeg_args += [
                f'-c:a:{next_audio_stream_index}', encoder,
                f'-ac:a:{next_audio_stream_index}', str(chnls),
                f'-b:a:{next_audio_stream_index}', rate
            ]
        else:
            ffmpeg_args += [f'-c:a:{next_audio_stream_index}', 'copy']

        # Copy dispositions
        for disp_key, disp_val in existing_dispositions[abs_stream].items():
            if disp_val:
                if defaudio2ch and disp_key == 'default':
                    ffmpeg_args += [f'-disposition:a:{next_audio_stream_index}', '0']
                else:
                    ffmpeg_args += [f'-disposition:a:{next_audio_stream_index}', disp_key]

        next_audio_stream_index += 1

        # Add stereo downmix only if no stereo already exists
        if not stereo_exists and chnls > 2:
            rate = '128k'
            if 'bit_rate' in s:
                rate = str(int(int(s['bit_rate']) / (1000 * max(chnls, 1))) * 2) + 'k'

            filter_args = []
            if normalize_2_channel_stream:
                filter_args = [f"-filter:a:{next_audio_stream_index}", audio_filtergraph(settings)]

            orig_title = s.get('tags', {}).get('title')
            new_title = f"{orig_title} - 2.0" if orig_title else "Stereo"

            ffmpeg_args += [
                '-map', f'0:{abs_stream}',
                f'-c:a:{next_audio_stream_index}', encoder,
                f'-ac:a:{next_audio_stream_index}', '2',
                f'-b:a:{next_audio_stream_index}', rate,
                f'-metadata:s:a:{next_audio_stream_index}', f"title={new_title}"
            ] + filter_args

            if defaudio2ch:
                ffmpeg_args += [f'-disposition:a:{next_audio_stream_index}', 'default']

            next_audio_stream_index += 1

    # Map subtitles/data/attachments and restore dispositions
    subtitle_streams = [s for s in probe_streams if s['codec_type'] == 'subtitle']
    data_streams = [s for s in probe_streams if s['codec_type'] == 'data']
    attachment_streams = [s for s in probe_streams if s['codec_type'] == 'attachment']

    ffmpeg_args += ['-map', '0:s?', '-c:s', 'copy']
    for i, s in enumerate(subtitle_streams):
        for disp_key, disp_val in existing_dispositions[s['index']].items():
            if disp_val:
                ffmpeg_args += [f'-disposition:s:{i}', disp_key]

    ffmpeg_args += ['-map', '0:d?', '-c:d', 'copy']
    for i, s in enumerate(data_streams):
        for disp_key, disp_val in existing_dispositions[s['index']].items():
            if disp_val:
                ffmpeg_args += [f'-disposition:d:{i}', disp_key]

    ffmpeg_args += ['-map', '0:t?', '-c:t', 'copy']
    for i, s in enumerate(attachment_streams):
        for disp_key, disp_val in existing_dispositions[s['index']].items():
            if disp_val:
                ffmpeg_args += [f'-disposition:t:{i}', disp_key]

    ffmpeg_args += ['-y', str(outpath)]

    logger.debug(f"ffmpeg args: '{ffmpeg_args}'")

    data['exec_command'] = ['ffmpeg'] + ffmpeg_args
    parser = Parser(logger)
    parser.set_probe(probe_data)
    data['command_progress_parser'] = parser.parse_progress

    return data
