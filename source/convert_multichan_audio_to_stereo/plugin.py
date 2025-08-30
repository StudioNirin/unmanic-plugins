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
from unmanic.libs.unplugins.settings import PluginSettings
from convert_multichan_audio_to_stereo.lib.ffmpeg import Probe, Parser

logger = logging.getLogger("Unmanic.Plugin.convert_multichan_audio_to_stereo")


def has_stereo_track(probe_streams):
    return any(
        s['codec_type'] == 'audio' and s.get('channels', 0) == 2
        for s in probe_streams
    )


class Settings(PluginSettings):
    settings = {
        "use_libfdk_aac": True,
        "encode_all_2_aac": True,
        "keep_mc": True,
        "set_2ch_stream_as_default": False,
        "normalize_2_channel_stream": True,
        'I': '-16.0',
        'LRA': '11.0',
        'TP': '-1.5',
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)
        self.form_settings = {
            "use_libfdk_aac": {"label": "check if you want to use libfdk_aac (requires ffmpeg >= 5), otherwise native aac is used"},
            "encode_all_2_aac": {"label": "check this if you want to re-encode all existing streams to AAC"},
            "keep_mc": {"label": "uncheck to delete multichannel streams after downmixing"},
            "set_2ch_stream_as_default": {"label": "check to set default audio stream as the new 2 channel stream"},
            "normalize_2_channel_stream": {"label": "check to normalize resulting 2 channel audio stream"},
            "I": self.__set_I_form_settings(),
            "LRA": self.__set_LRA_form_settings(),
            "TP": self.__set_TP_form_settings(),
        }

    def __set_I_form_settings(self):
        values = {"label": "Integrated loudness target", "input_type": "slider", "slider_options": {"min": -70.0, "max": -5.0, "step": 0.1}}
        if not self.get_setting('normalize_2_channel_stream'):
            values["display"] = 'hidden'
        return values

    def __set_LRA_form_settings(self):
        values = {"label": "Loudness range", "input_type": "slider", "slider_options": {"min": 1.0, "max": 20.0, "step": 0.1}}
        if not self.get_setting('normalize_2_channel_stream'):
            values["display"] = 'hidden'
        return values

    def __set_TP_form_settings(self):
        values = {"label": "The maximum true peak", "input_type": "slider", "slider_options": {"min": -9.0, "max": 0, "step": 0.1}}
        if not self.get_setting('normalize_2_channel_stream'):
            values["display"] = 'hidden'
        return values


def streams_to_stereo_encode(probe_streams):
    stereo_langs = [
        s['tags']['language']
        for s in probe_streams
        if s['codec_type'] == 'audio' and s.get('channels', 0) == 2
        and 'tags' in s and 'language' in s['tags']
        and (("title" not in s['tags']) or ("commentary" not in s['tags'].get("title", "").lower()))
    ]

    streams = []
    for s in probe_streams:
        if s['codec_type'] == 'audio' and s.get('channels', 0) > 2:
            if 'tags' in s and 'language' in s['tags'] and s['tags']['language'] not in stereo_langs:
                streams.append(s['index'])
    return streams


def on_library_management_file_test(data):
    abspath = data.get('path')
    probe_data = Probe(logger, allowed_mimetypes=['audio', 'video'])

    if not probe_data.file(abspath):
        logger.debug("Probe data failed - Blocking everything.")
        data['add_file_to_pending_tasks'] = False
        return data

    probe_streams = probe_data.get_probe()["streams"]
    settings = Settings(library_id=data.get('library_id')) if data.get('library_id') else Settings()

    streams_to_downmix = [] if has_stereo_track(probe_streams) else streams_to_stereo_encode(probe_streams)
    streams_to_aac_encode_list = []
    if settings.get_setting('encode_all_2_aac'):
        streams_to_aac_encode_list = [s['index'] for s in probe_streams if s['codec_type'] == 'audio']

    if streams_to_downmix or streams_to_aac_encode_list:
        data['add_file_to_pending_tasks'] = True
        for stream in streams_to_downmix:
            logger.debug(f"Audio stream '{stream}' is multichannel audio - convert stream")
    else:
        logger.debug(f"Do not add file '{abspath}' to task list - no audio streams to process")

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
    settings = Settings(library_id=data.get('library_id')) if data.get('library_id') else Settings()

    keep_mc = settings.get_setting('keep_mc')
    defaudio2ch = settings.get_setting('set_2ch_stream_as_default')
    normalize_2_channel_stream = settings.get_setting('normalize_2_channel_stream')
    encode_all_2_aac = settings.get_setting('encode_all_2_aac')
    encoder = 'libfdk_aac' if settings.get_setting('use_libfdk_aac') else 'aac'

    streams_to_downmix = [] if has_stereo_track(probe_streams) else streams_to_stereo_encode(probe_streams)
    streams_to_aac = [s['index'] for s in probe_streams if s['codec_type'] == 'audio'] if encode_all_2_aac else []

    if not streams_to_downmix and not streams_to_aac:
        logger.debug(f"Do not add file '{abspath}' to task list - no audio streams to process")
        return data

    existing_dispositions = {s['index']: s.get('disposition', {}).copy() for s in probe_streams}

    ffmpeg_args = ['-hide_banner', '-loglevel', 'info', '-i', str(abspath), '-max_muxing_queue_size', '9999', '-map', '0:v', '-c:v', 'copy']
    next_audio_stream_index = 0

    for s in probe_streams:
        idx = s['index']
        chnls = s.get('channels', 2)

        # Set codec
        codec = encoder if idx in streams_to_aac else 'copy'

        # 64k per channel
        if idx in streams_to_aac:
            bitrate = 64000 * chnls
            rate = str(int(bitrate / 1000)) + 'k'
        else:
            rate = None

        ffmpeg_args += ['-map', f'0:{idx}', f'-c:a:{next_audio_stream_index}', codec]
        if rate:
            ffmpeg_args += [f'-b:a:{next_audio_stream_index}', rate]

        # Downmix if needed
        if idx in streams_to_downmix:
            ffmpeg_args += [f'-ac:a:{next_audio_stream_index}', '2', f'-metadata:s:a:{next_audio_stream_index}', 'title=Stereo']
            if normalize_2_channel_stream:
                ffmpeg_args += [f'-filter:a:{next_audio_stream_index}', audio_filtergraph(settings)]

        # Dispositions
        for disp_key, disp_val in existing_dispositions[idx].items():
            if disp_val:
                if defaudio2ch and idx in streams_to_downmix and disp_key == 'default':
                    ffmpeg_args += [f'-disposition:a:{next_audio_stream_index}', '0']
                else:
                    ffmpeg_args += [f'-disposition:a:{next_audio_stream_index}', disp_key]
        if defaudio2ch and idx in streams_to_downmix:
            ffmpeg_args += [f'-disposition:a:{next_audio_stream_index}', 'default']

        next_audio_stream_index += 1

    # Map subtitles/data/attachments
    ffmpeg_args += ['-map', '0:s?', '-c:s', 'copy', '-map', '0:d?', '-c:d', 'copy', '-map', '0:t?', '-c:t', 'copy', '-y', str(outpath)]

    logger.debug(f"ffmpeg args: '{ffmpeg_args}'")

    data['exec_command'] = ['ffmpeg'] + ffmpeg_args
    parser = Parser(logger)
    parser.set_probe(probe_data)
    data['command_progress_parser'] = parser.parse_progress

    return data
