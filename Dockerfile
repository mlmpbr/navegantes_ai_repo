# Usa uma imagem oficial do Python como base
FROM python:3.9

# Define o diretório de trabalho dentro do container para /code
WORKDIR /code

# Copia o arquivo de requisitos para dentro do container
COPY ./requirements.txt /code/requirements.txt

# Instala as dependências listadas no requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copia todo o conteúdo da sua pasta local (app.py, dados_cache, etc) para o container
COPY . /code

# Garante que a pasta de cache exista e tenha permissões de escrita (chmod 777)
# Isso é CRUCIAL para evitar erros de "Permission denied" ao tentar salvar os CSVs
RUN mkdir -p /code/dados_cache && chmod 777 /code/dados_cache

# Comando para iniciar a aplicação Dash usando Gunicorn
# -b 0.0.0.0:7860 -> O Hugging Face EXIGE que a aplicação rode na porta 7860
# app:server -> Procura o objeto 'server' dentro do arquivo 'app.py'
CMD ["gunicorn", "-b", "0.0.0.0:7860", "app:server"]