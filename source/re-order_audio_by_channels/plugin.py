#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    reorder_audio_streams_by_channels

    Unmanic plugin to reorder audio streams by number of channels.
    Highest channel count first (7.1 -> 5.1 -> 2.0 -> 1.0).

    Based on Josh.5's language reordering plugin, simplified for channel sorting.
"""

import logging

from reorder_audio_streams_by_language.lib.ffmpeg import Parser, Probe, StreamMapper

# Configure plugin logger
logger = logging.getLogger("Unmanic.Plugin.reorder_audio_streams_by_channels")


class PluginStreamMapper(StreamMapper):
    def __init__(self, abspath):
        # Check all streams (video, audio, subs, etc.)
        super(PluginStreamMapper, self).__init__(
            logger, ["video", "audio", "subtitle", "data", "attachment"]
        )
        self.abspath = abspath
        self.stream_type = "audio"

        # For storing stream ordering
        self.audio_streams = []   # list of (channels, stream_id)
        self.other_streams = []   # passthrough others

    def test_stream_needs_processing(self, stream_info: dict):
        # Always handle streams in custom mapper
        return True

    def custom_stream_mapping(self, stream_info: dict, stream_id: int):
        ident = {
            "video": "v",
            "audio": "a",
            "subtitle": "s",
            "data": "d",
            "attachment": "t",
        }
        codec_type = stream_info.get("codec_type").lower()

        if codec_type == self.stream_type:
            channels = int(stream_info.get("channels", 0))
            self.audio_streams.append((channels, stream_id))
        else:
            self.other_streams.append((codec_type, stream_id))

        return {"stream_mapping": [], "stream_encoding": []}

    def streams_to_be_reordered(self):
        self.streams_need_processing()
        if not self.audio_streams or len(self.audio_streams) < 2:
            return False

        # Sorted vs original order
        sorted_streams = sorted(self.audio_streams, key=lambda x: x[0], reverse=True)
        return sorted_streams != self.audio_streams

    def order_stream_mapping(self):
        args = ["-c", "copy", "-disposition:a", "0"]  # reset dispositions
        ident = {"video": "v", "audio": "a", "subtitle": "s", "data": "d", "attachment": "t"}

        # Map all non-audio streams in original order
        for codec_type, stream_id in self.other_streams:
            args += ["-map", f"0:{ident.get(codec_type)}:{stream_id}"]

        # Map audio streams sorted by channel count
        for idx, (channels, stream_id) in enumerate(
            sorted(self.audio_streams, key=lambda x: x[0], reverse=True)
        ):
            if idx == 0:
                args += [
                    "-map", f"0:a:{stream_id}",
                    f"-disposition:a:{idx}", "default"
                ]
            else:
                args += ["-map", f"0:a:{stream_id}"]

        self.advanced_options += args


def on_library_management_file_test(data):
    abspath = data.get("path")

    probe = Probe(logger, allowed_mimetypes=["video"])
    if not probe.file(abspath):
        return data

    mapper = PluginStreamMapper(abspath)
    mapper.set_probe(probe)

    if mapper.streams_to_be_reordered():
        data["add_file_to_pending_tasks"] = True
        logger.debug(f"File '{abspath}' should be added to task list. Audio requires reordering.")
    else:
        logger.debug(f"File '{abspath}' audio already ordered.")

    return data


def on_worker_process(data):
    data["exec_command"] = []
    data["repeat"] = False

    abspath = data.get("file_in")

    probe = Probe(logger, allowed_mimetypes=["video"])
    if not probe.file(abspath):
        return data

    mapper = PluginStreamMapper(abspath)
    mapper.set_probe(probe)

    if mapper.streams_to_be_reordered():
        mapper.set_input_file(abspath)
        mapper.set_output_file(data.get("file_out"))
        mapper.order_stream_mapping()

        ffmpeg_args = mapper.get_ffmpeg_args()
        logger.debug(f"ffmpeg_args: '{ffmpeg_args}'")

        data["exec_command"] = ["ffmpeg"] + ffmpeg_args

        parser = Parser(logger)
        parser.set_probe(probe)
        data["command_progress_parser"] = parser.parse_progress

    return data
