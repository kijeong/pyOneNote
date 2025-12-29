# pyOneNote
pyOneNote is a lightweight python library to read OneNote files. The main goal of this parser is to allow cybersecurity analyst to extract useful information from OneNote files.

# Installing the parser

Installing the latest development

```
pip install -U https://github.com/DissectMalware/pyOneNote/archive/master.zip --force
```
# Running the parser

To dump all embedded file in current directory
```
pyonenote -f example.one 
```

To dump all embedded file in example.one into output_dir
```
pyonenote -f example.one -o output_dir 
```
To dump all embedded file in example.one into output_dir and add .bin to the end of each filename
```
pyonenote -f example.one -o output_dir -e bin
```

# Command Line
```
usage: pyonenote [-h] -f FILE [-o OUTPUT_DIR] [-e EXTENSION] [-j [JSON_PATH]]
                [--json-include SECTIONS] [--json-files-no-content]
```

## JSON output

- **Print JSON to stdout**
```
pyonenote -f example.one -j
```

- **Write JSON to a file**
```
pyonenote -f example.one -j output.json
```

- **Include only selected JSON sections**
```
pyonenote -f example.one -j --json-include headers,links
```

- **Omit embedded file content and include SHA-256 hash**
```
pyonenote -f example.one -j --json-include files --json-files-no-content
```

Note: pyOneNote is under active development

# How to Contribute
If you found a bug or would like to suggest an improvement, please create a new issue on the [issues page](https://github.com/DissectMalware/pyOneNote/issues).

Feel free to contribute to the project forking the project and submitting a pull request.

You can reach [me (@DissectMlaware) on Twitter](https://twitter.com/DissectMalware) via a direct message.
