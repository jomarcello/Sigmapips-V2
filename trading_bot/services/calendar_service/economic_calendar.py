import urllib
import urllib.request
from urllib.error import HTTPError

from bs4 import BeautifulSoup
import datetime
import arrow


class Good():
	def __init__(self):
		self.value = "+"
		self.name = "good"

	def __repr__(self):
		return "<Good(value='%s')>" % (self.value)


class Bad():
	def __init__(self):
		self.value = "-"
		self.name = "bad"

	def __repr__(self):
		return "<Bad(value='%s')>" % (self.value)


class Unknow():
	def __init__(self):
		self.value = "?"
		self.name = "unknow"

	def __repr__(self):
		return "<Unknow(value='%s')>" % (self.value)		


class Investing():
	def __init__(self, uri='https://www.investing.com/economic-calendar/'):
		self.uri = uri
		self.req = urllib.request.Request(uri)
		self.req.add_header('User-Agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/51.0.2704.103 Safari/537.36')
		self.result = []
		self.major_countries = [
			'United States',
			'Euro Zone',
			'United Kingdom',
			'Japan',
			'Switzerland',
			'Canada',
			'Australia',
			'New Zealand'
		]

	def news(self):
		try:
			response = urllib.request.urlopen(self.req)
			
			html = response.read()
			
			soup = BeautifulSoup(html, "html.parser")

			# Find event item fields
			table = soup.find('table', {"id": "economicCalendarData"})
			tbody = table.find('tbody')
			rows = tbody.find_all('tr', {"class": "js-event-item"})

			for tr in rows:
				news = {'timestamp': None,
						'country': None,
						'impact': None,
						'url': None,
						'name': None,
						'bold': None,
						'fore': None,
						'prev': None,
						'signal': None,
						'type': None}
				
				_datetime = tr.attrs['data-event-datetime']
				news['timestamp'] = arrow.get(_datetime, "YYYY/MM/DD HH:mm:ss").timestamp()

				cols = tr.find('td', {"class": "flagCur"})
				flag = cols.find('span')

				news['country'] = flag.get('title')

				# Skip if not a major currency country
				if news['country'] not in self.major_countries:
					continue

				impact = tr.find('td', {"class": "sentiment"})
				bull = impact.find_all('i', {"class": "grayFullBullishIcon"})

				news['impact'] = len(bull)

				event = tr.find('td', {"class": "event"})
				a = event.find('a')

				news['url'] = "https://www.investing.com{}".format(a['href'])
				news['name'] = a.text.strip()

				# Determite type of event
				legend = event.find('span', {"class": "smallGrayReport"})
				if legend:
					news['type'] = "report"

				legend = event.find('span', {"class": "audioIconNew"})
				if legend:
					news['type'] = "speech"

				legend = event.find('span', {"class": "smallGrayP"})
				if legend:
					news['type'] = "release"
				
				legend = event.find('span', {"class": "sandClock"})
				if legend:
					news['type'] = "retrieving data"					


				bold = tr.find('td', {"class": "bold"})

				if bold.text != '':
					news['bold'] = bold.text.strip()
				else:
					news['bold'] = ''

				fore = tr.find('td', {"class": "fore"})
				news['fore'] = fore.text.strip()

				prev = tr.find('td', {"class": "prev"})
				news['prev'] = prev.text.strip()

				if "blackFont" in bold['class']:
					news['signal'] = Unknow()

				elif "redFont" in bold['class']:
					news['signal'] = Bad()

				elif "greenFont" in bold['class']:
					news['signal'] = Good()

				else:
					news['signal'] = Unknow()

				self.result.append(news)
		
		except HTTPError as error:
			print ("Oops... Get error HTTP {}".format(error.code))

		return self.result


if __name__ == "__main__":
	i = Investing('https://www.investing.com/economic-calendar/')
	results = i.news()
	
	# Get today's date
	today = datetime.datetime.now().date()
	
	# Filter and sort events
	today_events = []
	for result in results:
		event_date = datetime.datetime.fromtimestamp(result['timestamp']).date()
		if event_date == today:
			today_events.append(result)
	
	# Sort by timestamp
	today_events.sort(key=lambda x: x['timestamp'])
	
	# Telegram format output
	output = []
	output.append(f"📅 *Economische Kalender - {today.strftime('%d-%m-%Y')}*")
	output.append("=" * 30)
	
	for result in today_events:
		# Convert to Malaysian time (UTC+8)
		event_time = datetime.datetime.fromtimestamp(result['timestamp'])
		malaysian_time = event_time + datetime.timedelta(hours=8)
		
		impact_stars = "⭐" * result['impact']
		country_emoji = {
			'United States': '🇺🇸',
			'Euro Zone': '🇪🇺',
			'United Kingdom': '🇬🇧',
			'Japan': '🇯🇵',
			'Switzerland': '🇨🇭',
			'Canada': '🇨🇦',
			'Australia': '🇦🇺',
			'New Zealand': '🇳🇿'
		}.get(result['country'], '🌍')
		
		output.append(f"\n*{malaysian_time.strftime('%H:%M')}* {country_emoji} {result['country']}")
		output.append(f"📊 {result['name']}")
		output.append(f"Impact: {impact_stars}")
		
		if result['fore']:
			output.append(f"Voorspelling: {result['fore']}")
		if result['prev']:
			output.append(f"Vorige: {result['prev']}")
		if result['bold']:
			output.append(f"Actueel: {result['bold']}")
		
		output.append(f"Signaal: {result['signal'].value}")
		output.append("-" * 20)
	
	# Print in Telegram format
	print("\n".join(output)) 
