import codecs  # used for text encoding in config parser
import argparse  # good argument parser
from configparser import ConfigParser  # able to read configuration file

class config_loader():
    # config structure: short_option, long_option, setination_variable, help
    config = [{'-t', '--token', 'token', 'Backen access token'},
              {'-l', '--url-link'},
              {'-f', '--file', 'member_list_file', 'Group member list file'},
              {'-p', '--project', 'project', 'Project where calculate statistics'},
              {'-b', '--branch', 'branch', 'Branch for statistics calculation'},
              {'-d', '--date', 'date_start', True, 'query date string start, eg. 2019-06 or 2019-06-25'},
              {'-v', '--verbose', 'verbose', 'store_true', 'enable verbose (debug) logging'},
              {'-u', '--until', 'date_until', False, 'query date string until'}]


    def parse_arguments(self):
        #  argument parsing section
        tool_description = 'Track comments left in code by using Gerrit API'
        parser = argparse.ArgumentParser(description=tool_description,
                                         formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser.add_argument('-t', '--token', dest='token', help='token')
        parser.add_argument('-l', '--url-link', dest='base_url', help='the gerrit url')
        parser.add_argument('-f', '--file', dest='member_list_file', help='Group member list file')
        parser.add_argument('-p', '--project', dest='project', help='Project where calculate statistics')
        parser.add_argument('-b', '--branch', dest='branch', help='Branch for statistics calculation')
        parser.add_argument('-d', '--date', dest='date_start', required=True,
                            help='query date string start, eg. 2019-06 or 2019-06-25')
        parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='enable verbose (debug) logging')
        parser.add_argument('-u', '--until', dest='date_until', required=False, help='query date string until')
        options = parser.parse_args()

        base_url = options.base_url
        token = options.token
        branch = options.branch
        project = options.project
        date_start = options.date_start
        date_until = options.date_until
        member_list_file = options.member_list_file
        log_level = options.verbose

        return {'base_url': base_url, 'token': token, 'branch': branch, 'project': project,
                'member_list_file': member_list_file, 'date_start': date_start, 'date_until': date_until,
                'log_level': log_level}

    def parse_options(self, CONFIG_FILE):
        config = ConfigParser()
        config.read_file(codecs.open(CONFIG_FILE, 'r', encoding='utf-8-sig'))

        return {'base_url': base_url, 'token': token, 'branch': branch, 'project': project,
                'member_list_file': member_list_file, 'date_start': date_start, 'date_until': date_until,
                'log_level': log_level}


def merge_args_options(self):
        for conf in
            if base_url is None:
                base_url = config.get(CONFI_POINT_LOCAL, CONFIG_BASE_URL)
            if token is None:
                token = config.get(CONFI_POINT_LOCAL, CONFIG_TOKEN)
            if branch is None:
                branch = config.get(CONFI_POINT_LOCAL, CONFIG_BRANCH)
            if project is None:
                project = config.get(CONFI_POINT_LOCAL, CONFIG_PROJECT)
            if member_list_file is None:
                member_list_file = config.get(CONFIG_POINT_GLOBAL, CONFIG_MEMBER_LIST)

            if base_url is None or token is None or member_list_file is None:
                raise ValueError("url or username or password of file is invalid")