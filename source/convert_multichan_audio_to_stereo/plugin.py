#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    plugins.__init__.py

    Written by:               Josh.5 <jsunnex@gmail.com>
    Date:                     23 Aug 2021, (20:38 PM)

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
import os

from unmanic.libs.unplugins.settings import PluginSettings

from convert_multichan_audio_to_stereo.lib.ffmpeg import Probe, Parser

# Configure plugin logger
logger = logging.getLogger("Unmanic.Plugin.convert_multichan_audio_to_stereo")


class Settings(PluginSettings):
    settings = {
        "use_libfdk_aac":            True,
        "encode_all_2_aac":          True,
        "keep_mc":                   True,
        "set_2ch_stream_as_default": False,
        "default_lang":              "",
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
                "label": "check to set the default audio stream as a new 2 channel stream OR an existing audio stream if file contains no multichannel streams and you wish to designate a specific language stream as the default audio stream",
            },
            "default_lang": self.__set_default_lang_form_settings(),
            "normalize_2_channel_stream": {
                "label": "check this to normalize the resulting 2 channel audio stream - customizeable settings will appear below when checked",
            },
            "I": self.__set_I_form_settings(),
            "LRA": self.__set_LRA_form_settings(),
            "TP": self.__set_TP_form_settings(),
        }

    def __set_default_lang_form_settings(self):
        values = {
            "label": "A single language of an existing stream to use as default audio stream per above - it's probably 3 letters",
            "input_type": "textarea",
        }
        if not self.get_setting('set_2ch_stream_as_default'):
            values["display"] = 'hidden'
        return values

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


def streams_to_aac_encode(probe_streams, streams, keep_mc):
    non_aac_streams = [
        i for i in range(len(probe_streams))
        if probe_streams[i]['codec_type'] == 'audio'
        and probe_streams[i]['codec_name'] != 'aac'
        and (
            (keep_mc and probe_streams[i]['channels'] > 2 and i in streams)
            or (probe_streams[i]['channels'] == 2)
        )
    ]
    return non_aac_streams


def on_library_management_file_test(data):
    abspath = data.get('path')
    probe_data = Probe(logger, allowed_mimetypes=['audio', 'video'])

    if probe_data.file(abspath):
        probe_streams = probe_data.get_probe()["streams"]
    else:
        logger.debug("Probe data failed - Blocking everything.")
        data['add_file_to_pending_tasks'] = False
        return data

    if data.get('library_id'):
        settings = Settings(library_id=data.get('library_id'))
    else:
        settings = Settings()

    streams = streams_to_stereo_encode(probe_streams)
    encode_all_2_aac = settings.get_setting('encode_all_2_aac')
    keep_mc = settings.get_setting('keep_mc')
    streams_2_aac_encode = []
    if encode_all_2_aac:
        streams_2_aac_encode = streams_to_aac_encode(probe_streams, streams, keep_mc)

    if streams or streams_2_aac_encode:
        data['add_file_to_pending_tasks'] = True
        for stream in streams:
            logger.debug("Audio stream '{}' is multichannel audio - convert stream".format(stream))
    else:
        logger.debug("do not add file '{}' to task list - no multichannel audio streams".format(abspath))

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
    def2chlang = settings.get_setting('default_lang')
    encode_all_2_aac = settings.get_setting('encode_all_2_aac')
    normalize_2_channel_stream = settings.get_setting('normalize_2_channel_stream')
    encoder = 'libfdk_aac' if settings.get_setting('use_libfdk_aac') else 'aac'
    copy_enc = encoder if encode_all_2_aac else 'copy'

    # Identify streams
    streams = streams_to_stereo_encode(probe_streams)
    streams_2_aac_encode = streams_to_aac_encode(probe_streams, streams, keep_mc) if encode_all_2_aac else []
    all_astreams = [s['index'] for s in probe_streams if s['codec_type'] == 'audio']

    logger.debug(f"streams to downmix: {streams}")
    logger.debug(f"all audio streams: {all_astreams}")

    if not streams and not streams_2_aac_encode:
        logger.debug(f"do not add file '{abspath}' to task list - no multichannel audio streams")
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

        # Keep original
        ffmpeg_args += [
            '-map', f'0:{abs_stream}',
            f'-c:a:{next_audio_stream_index}', 'copy'
        ]
        for disp_key, disp_val in existing_dispositions[abs_stream].items():
            if disp_val:
                ffmpeg_args += [f'-disposition:a:{next_audio_stream_index}', disp_key]
        next_audio_stream_index += 1

        # Add stereo if multichannel
        if abs_stream in streams:
            rate = '128k'
            if 'bit_rate' in s:
                rate = str(int(int(s['bit_rate']) / (1000 * max(chnls, 1))) * 2) + 'k'

            filter_args = []
            if normalize_2_channel_stream:
                filter_args = [f"-filter:a:{next_audio_stream_index}", audio_filtergraph(settings)]

            # Title logic
            orig_title = s['tags'].get('title')
            lang = s['tags'].get('language', 'und').title()
            if orig_title:
                new_title = f"{orig_title} - 2.0"
            else:
                new_title = f"Stereo"

            ffmpeg_args += [
                '-map', f'0:{abs_stream}',
                f'-c:a:{next_audio_stream_index}', encoder,
                f'-ac:a:{next_audio_stream_index}', '2',
                f'-b:a:{next_audio_stream_index}', rate,
                f'-metadata:s:a:{next_audio_stream_index}', f"title={new_title}"
            ] + filter_args

            if defaudio2ch and s.get('tags', {}).get('language') == def2chlang:
                ffmpeg_args += [f'-disposition:a:{next_audio_stream_index}', 'default']

            next_audio_stream_index += 1

    # Encode any extra 2ch tracks if requested
    for abs_stream in streams_2_aac_encode:
        if abs_stream in streams:
            continue
        s = probe_streams[abs_stream]
        chnls = s.get('channels', 0)
        rate = '128k'
        if 'bit_rate' in s:
            rate = str(int(int(s['bit_rate']) / (1000 * max(chnls, 1))) * 2) + 'k'

        filter_args = []
        if normalize_2_channel_stream:
            filter_args = [f"-filter:a:{next_audio_stream_index}", audio_filtergraph(settings)]

        ffmpeg_args += [
            '-map', f'0:{abs_stream}',
            f'-c:a:{next_audio_stream_index}', encoder,
            f'-ac:a:{next_audio_stream_index}', '2',
            f'-b:a:{next_audio_stream_index}', rate
        ] + filter_args
        next_audio_stream_index += 1

    # Map subtitles/data/attachments
    ffmpeg_args += [
        '-map', '0:s?', '-c:s', 'copy',
        '-map', '0:d?', '-c:d', 'copy',
        '-map', '0:t?', '-c:t', 'copy',
        '-y', str(outpath)
    ]

    logger.debug(f"ffmpeg args: '{ffmpeg_args}'")

    data['exec_command'] = ['ffmpeg'] + ffmpeg_args
    parser = Parser(logger)
    parser.set_probe(probe_data)
    data['command_progress_parser'] = parser.parse_progress

    return data
