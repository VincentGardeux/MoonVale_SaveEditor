# Start from pythonnet image
FROM mosthege/pythonnet:python3.11.1-mono6.12-pythonnet3.0.1

# Update system
RUN apt update && apt upgrade -y      

# Upgrade pip
RUN python -m pip install --upgrade pip ipykernel ipyevents jupyter ipywidgets

