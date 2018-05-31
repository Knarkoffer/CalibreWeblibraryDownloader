# Calibre Weblibrary Downloader

Python-script to download books from a publicly accessible library. A great way to find new ones is by using [Shodan](https://www.shodan.io/search?query=%22server%3A+calibre%22)

### Prerequisites

* BeautifulSoup 
```
pip install beautifulsoup4
```

* fake-useragent
```
pip install fake-useragent
```
* Requests
```
pip install requests

```


## Usage
Just run the script and pass either an adress in the format of ip:port, or a file with lots of adresses (one per line).


## Note

You'll need to configure a path of where to save the downloaded books, the libraryStorage-variable. Also, I myself don't care for pdf's, so I'm ignoring them, but if you want those you'll have to adjust the code a bit.


## To-Do

* Add argparse to get a better grip of parameters. (Like: -f "EPUB, MOBI" for formats.)
* Remove reliance of fake-useragent by hardcoding a list of useragents. Don't know if this is better or not, might skip it.
* (Maybe) Figure out a way to redo the whole rule-handling, to be able to make more complex rules.
* (Maybe) Create a version which scrapes the pages using selenium, so as not to be limited to the mobile page and thereby getting a better metadata-selection, like Language, Tags, Series etc.


## Authors

* **Knarkoffer** - *Author* - [Knarkoffer](https://github.com/Knarkoffer)


## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details

## Acknowledgments

* Kovid Goyal for creating the excellent application calibre
* Thanks to the creators of BeautifulSoup for their excellent way of processing HTML-code
* Other creators of libraries I've used
