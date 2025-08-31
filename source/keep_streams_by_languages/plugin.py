#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    plugins.__init__.py

    Written by:               Josh.5 <jsunnex@gmail.com>, senorsmartypants@gmail.com, yajrendrag@gmail.com
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
import os
from configparser import NoSectionError, NoOptionError
import iso639

from unmanic.libs.unplugins.settings import PluginSettings
from unmanic.libs.directoryinfo import UnmanicDirectoryInfo

from keep_streams_by_languages.lib.ffmpeg import StreamMapper, Probe, Parser

# Configure plugin logger
logger = logging.getLogger("Unmanic.Plugin.keep_streams_by_languages")


class Settings(PluginSettings):
    settings = {
        "audio_languages":       '',
        "subtitle_languages":    '',
        "keep_undefined":        True,
        "keep_commentary":       False,
        "fail_safe":             True,
    }


    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)
        self.form_settings = {
            "audio_languages": {
                "label": "Enter comma delimited list of audio languages to keep",
            },
            "subtitle_languages": {
                "label": "Enter comma delimited list of subtitle languages to keep",
            },
            "keep_undefined":	{
                "label": "check to keep streams with no language tags or streams with undefined/unknown language tags",
            },
            "keep_commentary":   {
                "label": "uncheck to discard commentary audio streams regardless of any language tags",
            },
            "fail_safe":   {
                "label": "check to include fail safe check to prevent unintentional deletion of all audio &/or all subtitle streams",
            }
        }

class PluginStreamMapper(StreamMapper):
    def __init__(self):
        super(PluginStreamMapper, self).__init__(logger, ['audio','subtitle'])
        self._out_idx = {'a': -1, 's': -1}  # track output type-relative index per codec
        self.settings = None

    def set_settings(self, settings):
        self.settings = settings

    def null_streams(self, streams):
        alcl, audio_streams_list = streams_list(self.settings.get_setting('audio_languages'), streams, 'audio')
        slcl, subtitle_streams_list = streams_list(self.settings.get_setting('subtitle_languages'), streams, 'subtitle')
        if (any(l in audio_streams_list for l in alcl) or alcl == ['*'] or audio_streams_list == []) and (any(l in subtitle_streams_list for l in slcl) or slcl == ['*'] or subtitle_streams_list == []):
            return True
        logger.info("One of the lists of languages does not contain a language matching any streams in the file - the entire stream type would be removed if processed, aborting.\n alcl: '{}', audio streams in file: '{}';\n slcl: '{}', subtitle streams in file: '{}'".format(alcl, audio_streams_list, slcl, subtitle_streams_list))
        return False

    def same_streams_or_no_work(self, streams, keep_undefined):
        alcl, audio_streams_list = streams_list(self.settings.get_setting('audio_languages'), streams, 'audio')
        slcl, subtitle_streams_list = streams_list(self.settings.get_setting('subtitle_languages'), streams, 'subtitle')
#        if not audio_streams_list or not subtitle_streams_list:
#            return False
        untagged_streams = [i for i in range(len(streams)) if "codec_type" in streams[i] and streams[i]["codec_type"] in ["audio", "subtitle"] and ("tags" not in streams[i] or ("tags" in streams[i] and "language" not in streams[i]["tags"]))]

        # if subtitle or audio _streams_list is empty the "all" statements will not test properly so the if statements work around this
        # and then we set the audio/subtitle_in a/slcl to True so no_work_to_do is properly determined.
        if subtitle_streams_list and slcl != ['*']:
            subs_in_slcl = all(l in slcl for l in subtitle_streams_list)
        else:
            subs_in_slcl = True
        if audio_streams_list and alcl != ['*']:
            audio_in_alcl = all(l in alcl for l in audio_streams_list)
        else:
            audio_in_alcl = True
        no_work_to_do = (subs_in_slcl and audio_in_alcl and (keep_undefined == True or (keep_undefined == False and untagged_streams == [])))
        logger.debug("audio config list: '{}', audio streams in file: '{}'".format(alcl, audio_streams_list))
        logger.debug("subtitle config list: '{}', subtitle streams in file: '{}'".format(slcl, subtitle_streams_list))
        logger.debug("untagged streams: '{}'".format(untagged_streams))
        logger.debug("subs in slcl: '{}'; audio in alcl: '{}'".format(subs_in_slcl, audio_in_alcl))
        logger.debug("no work to do: '{}'".format(no_work_to_do))
        if ((alcl == audio_streams_list or alcl == ['*'])  and (slcl == subtitle_streams_list or slcl == ['*'])) or no_work_to_do:
            return True
        else:
            return False

    def test_tags_for_search_string(self, codec_type, stream_tags, stream_id):
        keep_undefined  = self.settings.get_setting('keep_undefined')
        # TODO: Check if we need to add 'title' tags
        if stream_tags and True in list(k.lower() in ['language'] for k in stream_tags):
            # check codec and get appropriate language list
            if codec_type == 'audio':
                language_list = self.settings.get_setting('audio_languages')
            else:
                language_list = self.settings.get_setting('subtitle_languages')
            languages = list(filter(None, language_list.split(',')))
            languages = [languages[i].strip() for i in range(len(languages))]
            if '*' not in languages and languages:
                try:
                    languages = [iso639.Language.match(languages[i]).part1 if iso639.Language.match(languages[i]).part1 is not None and languages[i] in iso639.Language.match(languages[i]).part1 else
                                 iso639.Language.match(languages[i]).part2b if iso639.Language.match(languages[i]).part2b is not None and languages[i] in iso639.Language.match(languages[i]).part2b else
                                 iso639.Language.match(languages[i]).part2t if iso639.Language.match(languages[i]).part2t is not None and languages[i] in iso639.Language.match(languages[i]).part2t else
                                 iso639.Language.match(languages[i]).part3 if languages[i] in iso639.Language.match(languages[i]).part3 else "" for i in range(len(languages))]
                except iso639.language.LanguageNotFoundError:
                    raise iso639.language.LanguageNotFoundError("config list: ", languages)

            for language in languages:
                language = language.strip()
                try:
                    stream_tag_language = iso639.Language.match(stream_tags.get('language', '').lower()).part1 if iso639.Language.match(stream_tags.get('language', '').lower()).part1 is not None and stream_tags.get('language', '').lower() in iso639.Language.match(stream_tags.get('language', '').lower()).part1 else \
                                          iso639.Language.match(stream_tags.get('language', '').lower()).part2b if iso639.Language.match(stream_tags.get('language', '').lower()).part2b is not None and stream_tags.get('language', '').lower() in iso639.Language.match(stream_tags.get('language', '').lower()).part2b else \
                                          iso639.Language.match(stream_tags.get('language', '').lower()).part2t if iso639.Language.match(stream_tags.get('language', '').lower()).part2t is not None and stream_tags.get('language', '').lower() in iso639.Language.match(stream_tags.get('language', '').lower()).part2t else \
                                          iso639.Language.match(stream_tags.get('language', '').lower()).part3 if iso639.Language.match(stream_tags.get('language', '').lower()).part3 is not None and stream_tags.get('language', '').lower() in iso639.Language.match(stream_tags.get('language', '').lower()).part3 else ""
                except iso639.language.LanguageNotFoundError:
                    raise iso639.language.LanguageNotFoundError("stream tag language: ", stream_tags.get('language', '').lower())
                if language and (language.lower() in stream_tag_language or language.lower() == '*'):
                    return True
        elif keep_undefined:
            logger.warning(
                "Stream '{}' in file '{}' has no language tag, but keep_undefined is checked. add to queue".format(stream_id, self.input_file))
            return True

        else:
            logger.warning(
                "Stream '{}' in file '{}' has no language tag. Ignoring".format(stream_id, self.input_file))
        return False

    def test_stream_needs_processing(self, stream_info: dict):
        """Only add streams that have language task that match our list"""
        return self.test_tags_for_search_string(stream_info.get('codec_type', '').lower(), stream_info.get('tags'), stream_info.get('index'))

    def custom_stream_mapping(self, stream_info: dict, stream_id: int):
        """Remove this stream"""
        return {
            'stream_mapping':  [],
            'stream_encoding': [],
        }

def streams_list(languages, streams, stream_type):
    language_config_list = languages
    lcl = list(language_config_list.split(','))
    lcl = [lcl[i].strip() for i in range(0,len(lcl))]
    lcl.sort()
    if lcl == ['']: lcl = []
    if '*' not in lcl and lcl:
        try:
            lcl = [iso639.Language.match(lcl[i]).part1 if iso639.Language.match(lcl[i]).part1 is not None and lcl[i] in iso639.Language.match(lcl[i]).part1 else
                   iso639.Language.match(lcl[i]).part2b if iso639.Language.match(lcl[i]).part2b is not None and lcl[i] in iso639.Language.match(lcl[i]).part2b else
                   iso639.Language.match(lcl[i]).part2t if iso639.Language.match(lcl[i]).part2t is not None and lcl[i] in iso639.Language.match(lcl[i]).part2t else
                   iso639.Language.match(lcl[i]).part3 if lcl[i] in iso639.Language.match(lcl[i]).part3 else "" for i in range(len(lcl))]
        except iso639.language.LanguageNotFoundError:
            raise iso639.language.LanguageNotFoundError("config list: ", lcl)
    try:
        streams_list = [streams[i]["tags"]["language"] for i in range(0, len(streams)) if "codec_type" in streams[i] and streams[i]["codec_type"] == stream_type]
        streams_list.sort() 
    except KeyError:
        streams_list = []
        logger.info("no '{}' tags in file".format(stream_type))
    if streams_list:
        try:
            streams_list = [iso639.Language.match(streams_list[i]).part1 if iso639.Language.match(streams_list[i]).part1 is not None and streams_list[i] in iso639.Language.match(streams_list[i]).part1 else
                            iso639.Language.match(streams_list[i]).part2b if iso639.Language.match(streams_list[i]).part2b is not None and streams_list[i] in iso639.Language.match(streams_list[i]).part2b else
                            iso639.Language.match(streams_list[i]).part2t if iso639.Language.match(streams_list[i]).part2t is not None and streams_list[i] in iso639.Language.match(streams_list[i]).part2t else
                            iso639.Language.match(streams_list[i]).part3 if streams_list[i] in iso639.Language.match(streams_list[i]).part3 else "" for i in range(len(streams_list))]
        except iso639.language.LanguageNotFoundError:
            raise iso639.language.LanguageNotFoundError("streams list: ", streams_list)
    return lcl,streams_list

def kept_streams(settings):
    al = settings.get_setting('audio_languages')
    if not al:
        al = settings.settings.get('audio_languages')
    sl = settings.get_setting('subtitle_languages')
    if not sl:
        sl = settings.settings.get('subtitle_languages')
    ku = settings.get_setting('keep_undefined')
    if not ku:
        ku = settings.settings.get('keep_undefined')
    kc = settings.get_setting('keep_commentary')
    if not kc:
        kc = settings.settings.get('keep_commentary')
    fs = settings.get_setting('fail_safe')
    if not fs:
        fs = settings.settings.get('fail_safe')

    return 'kept_streams=audio_languages={}:subtitle_languages={}:keep_undefined={}:keep_commentary={}:fail_safe={}'.format(al, sl, ku, kc, fs)

def file_streams_already_kept(settings, path):
    directory_info = UnmanicDirectoryInfo(os.path.dirname(path))

    try:
        streams_already_kept = directory_info.get('keep_streams_by_languages', os.path.basename(path))
    except NoSectionError as e:
        streams_already_kept = ''
    except NoOptionError as e:
        streams_already_kept = ''
    except Exception as e:
        logger.debug("Unknown exception {}.".format(e))
        streams_already_kept = ''

    if streams_already_kept:
        logger.debug("File's streams were previously kept with {}.".format(streams_already_kept))
        return True

    # Default to...
    return False

def on_library_management_file_test(data):
    """
    Runner function - enables additional actions during the library management file tests.

    The 'data' object argument includes:
        path                            - String containing the full path to the file being tested.
        issues                          - List of currently found issues for not processing the file.
        add_file_to_pending_tasks       - Boolean, is the file currently marked to be added to the queue for processing.

    :param data:
    :return:

    """
    # Configure settings object (maintain compatibility with v1 plugins)
    if data.get('library_id'):
        settings = Settings(library_id=data.get('library_id'))
    else:
        settings = Settings()

    # If the config is empty (not yet configured) ignore everything
    if not settings.get_setting('audio_languages') and not settings.get_setting('subtitle_languages'):
        logger.debug("Plugin has not yet been configured with a list languages to remove allow. Blocking everything.")
        return False

    # Get the path to the file
    abspath = data.get('path')

    # Get file probe
    probe = Probe(logger, allowed_mimetypes=['video'])
    if not probe.file(abspath):
        # File probe failed, skip the rest of this test
        return data

    # get all streams
    probe_streams=probe.get_probe()["streams"]

    # Get stream mapper
    mapper = PluginStreamMapper()
    mapper.set_settings(settings)
    mapper.set_probe(probe)

    # Set the input file
    mapper.set_input_file(abspath)

    # Get fail-safe setting
    fail_safe = settings.get_setting('fail_safe')
    keep_undefined = settings.get_setting('keep_undefined')

    if not file_streams_already_kept(settings, abspath):
        logger.debug("File '{}' has not previously had streams kept by keep_streams_by_languages plugin".format(abspath))
        if fail_safe:
            if not mapper.null_streams(probe_streams):
                logger.debug("File '{}' does not contain streams matching any of the configured languages - if * was configured or the file has no streams of a given type, this check will not prevent the plugin from running for that strem type.".format(abspath))
                return data
        if mapper.same_streams_or_no_work(probe_streams, keep_undefined):
            logger.debug("File '{}' only has same streams as keep configuration specifies OR otherwise does not require any work to keep ony specified streams - so, does not contain streams that require processing.".format(abspath))
        elif mapper.streams_need_processing():
            # Mark this file to be added to the pending tasks
            data['add_file_to_pending_tasks'] = True
            logger.debug("File '{}' should be added to task list. Probe found streams require processing.".format(abspath))
        else:
            logger.debug("File '{}' does not contain streams that require processing.".format(abspath))

    del mapper

    return data

def keep_languages(mapper, ct, language_list, streams, keep_undefined, keep_commentary):
    codec_type_name = ct[0].lower()  # 'a' or 's'
    # normalise configured languages
    languages = [x.strip().lower() for x in filter(None, language_list.split(','))]
    if languages and '*' not in languages:
        try:
            languages = [(
                iso639.Language.match(L).part1 or
                iso639.Language.match(L).part2b or
                iso639.Language.match(L).part2t or
                iso639.Language.match(L).part3 or ""
            ) for L in languages]
        except iso639.language.LanguageNotFoundError:
            raise iso639.language.LanguageNotFoundError("config list: ", languages)

    # walk actual input streams of this type with their correct input type-index
    for in_type_idx, s in iter_type_streams(streams, ct):
        tags = s.get('tags', {})
        lang = (tags.get('language') or '').lower().strip()

        # commentary filter for audio
        if codec_type_name == 'a' and not keep_commentary:
            title = (tags.get('title') or '').lower()
            if 'commentary' in title:
                continue

        # undefined language handling
        if not lang:
            if keep_undefined:
                mapadder(mapper, in_type_idx, codec_type_name, s)
            continue

        # normalise stream language
        try:
            norm_lang = (
                iso639.Language.match(lang).part1 or
                iso639.Language.match(lang).part2b or
                iso639.Language.match(lang).part2t or
                iso639.Language.match(lang).part3 or ""
            )
        except iso639.language.LanguageNotFoundError:
            # if unknown language tag, treat as undefined if configured
            if keep_undefined:
                mapadder(mapper, in_type_idx, codec_type_name, s)
            continue

        # keep if matches config (or config is '*')
        if not languages or languages == ['*'] or norm_lang in languages:
            mapadder(mapper, in_type_idx, codec_type_name, s)


def keep_undefined(mapper, streams, keep_commentary):
    # Audio: respect commentary preference
    for in_type_idx, s in iter_type_streams(streams, 'audio'):
        tags = s.get('tags', {})
        lang = (tags.get('language') or '').strip().lower()
        if lang:
            continue
        if not keep_commentary:
            title = (tags.get('title') or '').lower()
            if 'commentary' in title:
                continue
        mapadder(mapper, in_type_idx, 'a', s)

    # Subtitles: keep truly untagged
    for in_type_idx, s in iter_type_streams(streams, 'subtitle'):
        lang = (s.get('tags', {}) .get('language') or '').strip().lower()
        if not lang:
            mapadder(mapper, in_type_idx, 's', s)


def iter_type_streams(streams, ct):
    """
    Yields (in_type_index, stream_dict) for each stream of codec_type == ct ('audio' or 'subtitle'),
    where in_type_index is the type-relative index (0,1,2...) in the *input*.
    """
    want = ct.lower()
    type_idx = 0
    for s in streams:
        if s.get('codec_type') == want:
            yield type_idx, s
            type_idx += 1

                
def mapadder(mapper, in_type_index, codec, stream_info):
    """
    Map one stream and preserve its original disposition flags by applying them
    to the correct *output* type-relative index.
    - in_type_index: type-relative index in the INPUT (e.g. s:0, a:1, ...)
    - codec: 'a' for audio, 's' for subtitle
    - stream_info: the actual probe stream dict for this stream
    """
    # 1) Map this exact input stream by type-relative index
    mapper.stream_mapping += ['-map', f'0:{codec}:{in_type_index}']

    # 2) Determine the output index this stream will get (increment per mapped stream of this codec)
    mapper._out_idx[codec] += 1
    out_idx = mapper._out_idx[codec]

    # 3) Clear any ffmpeg automatic disposition on THIS output stream
    mapper.stream_encoding += [f'-disposition:{codec}:{out_idx}', '0']

    # 4) Reapply only the flags that were set in the source for this stream
    disposition = (stream_info or {}).get('disposition', {})
    active_flags = [k for k, v in disposition.items() if v == 1]
    if active_flags:
        mapper.stream_encoding += [f'-disposition:{codec}:{out_idx}', '+'.join(active_flags)]


def on_worker_process(data):
    """
    Runner function - enables additional configured processing jobs during the worker stages of a task.

    The 'data' object argument includes:
        exec_command            - A command that Unmanic should execute. Can be empty.
        command_progress_parser - A function that Unmanic can use to parse the STDOUT of the command to collect progress stats. Can be empty.
        file_in                 - The source file to be processed by the command.
        file_out                - The destination that the command should output (may be the same as the file_in if necessary).
        original_file_path      - The absolute path to the original file.
        repeat                  - Boolean, should this runner be executed again once completed with the same variables.

    :param data:
    :return:

    """
    # Default to no FFMPEG command required. This prevents the FFMPEG command from running if it is not required
    data['exec_command'] = []
    data['repeat'] = False

    # Get the path to the file
    abspath = data.get('file_in')

    # Get file probe
    probe = Probe(logger, allowed_mimetypes=['video'])
    if not probe.file(abspath):
        # File probe failed, skip the rest of this test
        return data
    else:
        probe_streams = probe.get_probe()["streams"]

    # Configure settings object (maintain compatibility with v1 plugins)
    if data.get('library_id'):
        settings = Settings(library_id=data.get('library_id'))
    else:
        settings = Settings()

    keep_undefined_lang_tags = settings.get_setting('keep_undefined')
    keep_commentary = settings.get_setting('keep_commentary')

    if not file_streams_already_kept(settings, data.get('file_in')):
        # Get stream mapper
        mapper = PluginStreamMapper()
        mapper.set_settings(settings)
        mapper.set_probe(probe)

        # Set the input file
        mapper.set_input_file(abspath)

        # Get fail-safe setting
        fail_safe = settings.get_setting('fail_safe')

        # Test for null intersection of configured languages and actual languages
        if fail_safe:
            if not mapper.null_streams(probe_streams):
                logger.info("File '{}' does not contain streams matching any of the configured languages - if * was configured or the file has no streams of a given type, this check will not prevent the plugin from running for that strem type.".format(abspath))
                return data
        if mapper.same_streams_or_no_work(probe_streams, keep_undefined_lang_tags):
            logger.debug("File '{}' only has same streams as keep configuration specifies OR otherwise does not require any work to keep ony specified streams - so, does not contain streams that require processing.".format(abspath))
        elif mapper.streams_need_processing():
            logger.debug("File '{}' Proceeding with worker - probe found streams require processing.".format(abspath))
            # Set the output file
            mapper.set_output_file(data.get('file_out'))

            # clear stream mappings, copy all video
            mapper.stream_mapping = ['-map', '0:v']
            mapper.stream_encoding = []

            # keep specific language streams if present
            keep_languages(mapper, 'audio', settings.get_setting('audio_languages'), probe_streams, keep_undefined_lang_tags, keep_commentary)
            if settings.get_setting('subtitle_languages') != '*':
                keep_languages(mapper, 'subtitle', settings.get_setting('subtitle_languages'), probe_streams, keep_undefined_lang_tags, keep_commentary)

            # keep undefined language streams if present
            if keep_undefined_lang_tags:
                keep_undefined(mapper, probe_streams, keep_commentary)

            # All mapping must go through mapadder so dispositions are reset/reapplied.
            # (i.e., do NOT append a blanket '-map 0:s?' here.)
            mapper.stream_encoding += ['-c', 'copy']
            ffmpeg_args = mapper.get_ffmpeg_args()


            logger.debug("ffmpeg_args: '{}'".format(ffmpeg_args))

            # Apply ffmpeg args to command
            data['exec_command'] = ['ffmpeg']
            data['exec_command'] += ffmpeg_args

            # Set the parser
            parser = Parser(logger)
            parser.set_probe(probe)
            data['command_progress_parser'] = parser.parse_progress
        else:
            logger.debug("Worker will not process file '{}'; it does not contain streams that require processing.".format(abspath))
    return data

def on_postprocessor_task_results(data):
    """
    Runner function - provides a means for additional postprocessor functions based on the task success.

    The 'data' object argument includes:
        task_processing_success         - Boolean, did all task processes complete successfully.
        file_move_processes_success     - Boolean, did all postprocessor movement tasks complete successfully.
        destination_files               - List containing all file paths created by postprocessor file movements.
        source_data                     - Dictionary containing data pertaining to the original source file.

    :param data:
    :return:

    """
    # We only care that the task completed successfully.
    # If a worker processing task was unsuccessful, dont mark the file streams as kept
    # TODO: Figure out a way to know if a file's streams were kept but another plugin was the
    #   cause of the task processing failure flag
    if not data.get('task_processing_success'):
        return data

    # Configure settings object (maintain compatibility with v1 plugins)
    if data.get('library_id'):
        settings = Settings(library_id=data.get('library_id'))
    else:
        settings = Settings()

        
""" Preventing writing .unmanic file
    # Loop over the destination_files list and update the directory info file for each one
    for destination_file in data.get('destination_files'):
        directory_info = UnmanicDirectoryInfo(os.path.dirname(destination_file))
        directory_info.set('keep_streams_by_languages', os.path.basename(destination_file), kept_streams(settings))
        directory_info.save()
        logger.debug("Keep streams by languages already processed for '{}'.".format(destination_file))

    return data
"""
