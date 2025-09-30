# MoonVale_SaveEditor
Save Editor for MoonVale game (everbytes studio)

# Installation
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
