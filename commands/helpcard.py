import json
import webbrowser

import sublime
import sublime_plugin


class VexHelpcardCommand(sublime_plugin.TextCommand):
    '''Show documentation for function under cursor.'''

    def __init__(self, *args, **kwargs):
        self.css = sublime.load_resource('Packages/VEX/commands/helpcard.css')
        self.helpcards = json.loads(sublime.load_resource('Packages/VEX/commands/helpcards.json'))
        super().__init__(*args, **kwargs)

    def is_enabled(self):
        return self.view.score_selector(self.view.sel()[0].a, 'source.vex') > 0

    def run(self, edit):
        # Expand to full token under cursor.
        first_sel = self.view.sel()[0].a
        word = self.view.substr(self.view.word(first_sel))

        if word in self.helpcards:
            html = '<style>%s</style>%s' % (self.css, self.helpcards[word])
        else:
            # Not sure if search on Google CSE will always work. Will see...
            # Last cx parameter was: 001106583893786776783:4dnyszriw9c
            html = '''
            <style>{style}</style>

            <body>
                <h1>{term}</h1>
                <p class="summary">
                No popup help available for "{term}".
                </p>
                <p>Search online:
                    <a href="https://cse.google.com/cse?cx=001106583893786776783%3A4dnyszriw9c&q={term}">Docs</a> |
                    <a href="https://encrypted.google.com/search?&q=site%3Asidefx.com+OR+site%3Aodforce.net+{term}">Community</a> |
                    <a href="https://encrypted.google.com/search?&q={term}">Internet</a>
                </p>
            </body>
            '''.format(term=word, style=self.css)

        s = sublime.load_settings('VEX.sublime-settings')
        self.view.show_popup(html, on_navigate=webbrowser.open,
                             max_width=s.get('popup_max_width'),
                             max_height=s.get('popup_max_height'))
