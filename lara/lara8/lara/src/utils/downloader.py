def download_file(url, destination):
    import requests

    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Raise an error for bad responses

        with open(destination, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)

        print(f"File downloaded successfully to {destination}")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while downloading the file: {e}")

def download_files(urls, destination_folder):
    import os

    if not os.path.exists(destination_folder):
        os.makedirs(destination_folder)

    for url in urls:
        filename = os.path.join(destination_folder, url.split('/')[-1])
        download_file(url, filename)