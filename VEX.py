if __name__ != '__main__':
    from .commands import *

if __name__ == '__main__':
    # Collect package if runned as script.
    import os.path as op
    from os import walk
    from zipfile import ZipFile, ZIP_DEFLATED

    root = op.dirname(__file__)
    allow_dirs = (
        '.',
        'commands',
        'prefs',
        'snippets',
        'syntax',
    )
    allow_exts = (
        '.css',
        '.json',
        '.py',
        '.sublime-commands',
        '.sublime-completions',
        '.sublime-keymap',
        '.sublime-menu',
        '.sublime-settings',
        '.sublime-snippet',
        '.sublime-syntax',
        '.tmPreferences',
    )

    with ZipFile('VEX.sublime-package', 'w', ZIP_DEFLATED) as z:
        for folder, _, files in walk(root):
            folder = op.relpath(folder, root)
            if folder in allow_dirs:
                for f in files:
                    ext = op.splitext(f)[-1]
                    if ext in allow_exts:
                        z.write(op.join(folder, f))
