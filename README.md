# Calibre Weblibrary Downloader

Python-script to download books from a publicly accessible library. I've included a sample of IP's, which may or may not be outdated and offline at the time you are reading this. A great way to find new ones is by using [Shodan](https://www.shodan.io/search?query=%22server%3A+calibre%22)

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
## Note

You'll need to configure a path of where to save the downloaded books, the libraryStorage-variable. Also, I myself don't care for pdf's, so I'm ignoring them, but if you want those you'll have to adjust the code a bit.

## To-Do

* Maybe design some way to write a rule-file which can be used to process books (XML-based oribably). Note that I already have some rules that remove book I myself don't find interesting, like Star Wars/Star Trek.
* Add argparse to get a better grip of parameters. (Like: -f "EPUB, MOBI" for formats.)


## Authors

* **Knarkoffer** - *Author* - [Knarkoffer](https://github.com/Knarkoffer)

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details

## Acknowledgments

* Thanks to the creators of BeautifulSoup for their excellent way of processing HTML-code
* Other creators of libraries I've used
