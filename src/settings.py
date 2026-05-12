"""Scrapy settings module.

This module contains Scrapy settings for the project, defining various configurations and options.

For more comprehensive details on Scrapy settings, refer to the official documentation:
http://doc.scrapy.org/en/latest/topics/settings.html
"""

BOT_NAME = 'flashscore_odds'

LOG_LEVEL = 'INFO'

NEWSPIDER_MODULE = 'src.spiders'
SPIDER_MODULES = ['src.spiders']
ROBOTSTXT_OBEY = False

TELNETCONSOLE_ENABLED = False

CONCURRENT_REQUESTS = 16

# Do not change the Twisted reactor unless you really know what you are doing.
TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor'

ITEM_PIPELINES = {
    'src.pipelines.NullStripPipeline': 50,
    'src.pipelines.LimitItemsNumberPipeline': 100,
}

# No custom spider or downloader middlewares are needed.
SPIDER_MIDDLEWARES = {}
DOWNLOADER_MIDDLEWARES = {}
