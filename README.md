# MoonVale_SaveEditor
Save Editor for MoonVale game (everbytes studio)

# Usage
## 1) Dump for inspection
```bash
docker run --rm -it -v "$PWD:/work" mosthege/pythonnet:python3.11.1-mono6.12-pythonnet3.0.1 python /work/kat_edit.py dump /work/PersData.kat > save.json
```

## 2) Edit and save a new file (examples)
```bash
docker run --rm -it -v "$PWD:/work" mosthege/pythonnet:python3.11.1-mono6.12-pythonnet3.0.1 python /work/kat_edit.py edit /work/PersData.kat /work/Patched.kat --set coins=999999 --set diamonds=100000 --set username="Vincent"
```

# Installation (for further development)
## Docker image
First, you need to build a local Docker image using the [Dockerfile](Dockerfile) (here I call the local image "dotnet").

```bash
docker build . -t dotnet:latest
```

## [Optional] Create a JupyterNotebook kernel using the Docker image
Then, you can copy the provided kernel file: [kernel.json](kernel.json) to the Jupyter notebook kernel folder on your local machine.

e.g. on Linux, it is stored in /usr/local/share/jupyter/kernels/

# Running
You simply need to run the [test.ipynb](test.ipynb) script.
