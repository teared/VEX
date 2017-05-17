## Houdini add-on for Sublime Text
Syntax highligting, completions, snippets and documentation popups for VEX and HScript languages bundled with Houdini.


### Installation
See [Releases](https://github.com/teared/vex/releases).


### Features

#### VEX

![alt tag](https://raw.githubusercontent.com/teared/vex/master/develop/img/vex.png)

#### VEX Wrangle (and function completion)
Press `Ctrl+Space` or start typing to open completions list. Choose function you need. Navigate back and forth using `Tab` and `Shift+Tab`.

![alt tag](https://raw.githubusercontent.com/teared/vex/master/develop/img/wrangle.png)

#### Popups
Default shortcut is `Ctrl+Alt+D`, also available as command "VEX: Show Documentation for Function" in Command Palette.

![alt tag](https://raw.githubusercontent.com/teared/vex/master/develop/img/helpcard.png)

#### Compiler Errors
Press `F7` to build code and see compiler errors. Two build systems available in Command Palette:

1. `VEX Build` is an experimental and most useful: it will wrap source code into a function definition and build as CVex shader. It is possible to compile small pieces of code like wrangles.
2. `VEX Build - As Shader` is a simple wrapper for VCC, build VEX shaders with it.

It's not possible to evaluate expressions outside Houdini session, therefore they are not supported by this feature. Stuff like `$PI` or embedded backticks will produce syntax errors but will work normally inside Houdini. Evaluate parameter with middle mouse button and use resulting string as code.

![alt tag](https://raw.githubusercontent.com/teared/vex/master/develop/img/build.png)

#### HScript Expressions

![alt tag](https://raw.githubusercontent.com/teared/vex/master/develop/img/expressions.png)

#### HScript

![alt tag](https://raw.githubusercontent.com/teared/vex/master/develop/img/hscript.png)


### License
Public domain. Some files contains pieces of publicly available Houdini documentation. Such parts are property of SideFX.
