# Records docs/assets/cli.gif. Run from the repository root: vhs docs/cli.tape
Output docs/assets/cli.gif
Set Shell zsh
Set FontSize 15
Set Width 1480
Set Height 940
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms

Hide
Type "source .venv/bin/activate && cd examples && export PS1='$ ' && clear"
Enter
Show

Type "ragcompass analyze corpus"
Sleep 400ms
Enter
Sleep 9s

Type "clear && ragcompass analyze corpus -o ragcompass.yaml > /dev/null && sed -n '/^chunking/,$p' ragcompass.yaml"
Sleep 400ms
Enter
Sleep 7s
