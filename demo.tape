# VHS tape file for logler demo
# https://github.com/charmbracelet/vhs
#
# Generate: vhs demo.tape
# Output:   docs/demo.gif

Output docs/demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 960
Set Height 640
Set Theme "Catppuccin Mocha"
Set Padding 20

Type "# Logler -- Rust-powered log investigation"
Enter
Sleep 1s

Type "uv run python demo.py"
Enter
Sleep 8s
