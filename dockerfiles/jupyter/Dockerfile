FROM jupyter/minimal-notebook:latest

# Utilisateur par défaut dans l'image Jupyter : jovyan
USER root

# Installation des packages supplémentaires pour data science
RUN pip install --no-cache-dir \
    numpy \
    pandas \
    matplotlib \
    scikit-learn \
    plotly \
    ipywidgets

# Installation de l'extension JupyterLab Git
RUN pip install --no-cache-dir jupyterlab-git

# Réglage des permissions
RUN fix-permissions /home/jovyan

# Exposition du port pour Jupyter
EXPOSE 8888

# On revient à l'utilisateur jovyan pour démarrer Jupyter
USER jovyan

# Configuration de Jupyter sans token ou mot de passe pour faciliter l'accès
ENV JUPYTER_ENABLE_LAB=yes
CMD ["start-notebook.sh", "--NotebookApp.token=''", "--NotebookApp.password=''"]