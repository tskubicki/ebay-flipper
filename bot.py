import datetime, requests, json, time, schedule
import config

from urllib.parse import urlencode, quote_plus
from ebaysdk.exception import ConnectionError
from ebaysdk.finding import Connection

#items that may be worth trying to flip
potentials = [] 

ebay = Connection(
  appid=config.EBAY_API_KEY,
  config_file=None
)

#['1000','1500', '3000'] 'New', 'New(Other)', and 'Used'
#You can change 'condition' to be one or more of these numbers
#to consider these item conditions
#Be careful if using all conditions though, as this won't be as accurate 
condition = ['1000']

#Build a 'Completed Items' search query
#AKA, items that were successfully sold
def getCompletedListingsForUPC(upc_code):
  return {  
    'keywords': upc_code,
    'itemFilter': [
      #See above
      {'name':'Condition', 'value': condition},

      #change to match your location
      {'name': 'LocatedIn', 'value': 'US'},

      #Only concerned with 'Buy It Now' for now
      {'name': 'ListingType', 'value': ['FixedPrice','Auction']}, 

      #avoid factoring the zero feedback score scammers.
      #10 seems to be a decent limit, but you can change this to taste
      {'name': 'FeedbackScoreMin', 'value': 10},

      #We want the most recent sales
      {'name': 'SortOrder', 'value': 'StartTimeNewest'},

      #Don't bother us with stuff that didn't sell
      {'name': 'SoldItemsOnly', 'value': True},
    ]
  }

#standard item search query
def getActiveListingsForUPC(upc_code):
  return {  
    'keywords': upc_code,
    'itemFilter': [
        {'name':'Condition', 'value': condition},
        {'name': 'LocatedIn', 'value': 'US'},
        {'name': 'ListingType', 'value': 'FixedPrice'},
        {'name': 'FeedbackScoreMin', 'value': 10},
        {'name': 'SortOrder', 'value': 'PricePlusShippingLowest'},        
    ],
    'paginationInput':[
        {'name': 'EntriesPerPage', 'value': 100}
    ]
  }

def job():
  with open('upc_file.txt','r') as my_file:
    for upc in my_file:

      #Skip this UPC if it starts with a '#'
      if upc[0] == '#':
        continue
          
      #get raw data from ebay api
      response = ebay.execute(
        'findCompletedItems',
        getCompletedListingsForUPC(upc)
      ).dict()  

      #array of prices that will be averaged later
      avgs = []

      #pluck all the prices from the listings and add them to avgs list
      if response['searchResult'] and 'item' in response['searchResult']:
        for i in response['searchResult']['item']:  
          avgs.append(float(i['sellingStatus']['currentPrice']['value']))

      #If there are less than 10 items returned, the price is not 
      #very accurate. You can lower this if you want,
      #but keep it above 5 or you may have issues
      if len(avgs) < 10: 
        continue

      #Sort our prices in ascending order. Its easier for us later
      avgs = sorted(avgs)

      #flag the middle of the list of prices
      true_avg = sum(avgs)/len(avgs)

      #get the lowest and highest prices found for this UPC
      lowest_seen = avgs[0]
      highest_seen = avgs[-1]

      #How accurate is this set of prices, as in how many samples
      accuracy = len(avgs)


      #Great, we got our price data with which to make determinations with
      #Now, lets see whats on the market...

      #we got our averages - empty avgs list
      avgs = []

      #Fetch active listings for this upc
      response = ebay.execute(
        'findItemsAdvanced',
        getActiveListingsForUPC(upc)
      )    

      #If theres no active listing, forget it and try the next UPC
      if not hasattr(response.reply.searchResult, "item"):
        continue

      #Go through each result and see if it's a good flip or not
      #using the data we put together prior
      for index, item in enumerate(response.reply.searchResult.item):

        #pluck the price
        price = float(item.sellingStatus.convertedCurrentPrice.value)

        #The common ebay bait and switch scam listing uses
        #a MultiVariationListing to do the deed.
        #We don't care for them, so we ignore them
        if item.isMultiVariationListing == 'true':            
          continue 

        #Stop off further processing of this UPC if we've reached the items with
        #prices above average. No money to be made there, so no point  
        if price > true_avg*0.9:
          break         

        #get the price of the next item in the list
        #we'll use it soon
        next_highest_price = 1
        #(skip if this item is the last one)
        if index < len(response.reply.searchResult.item) - 2:          
          next_highest_price = float(
            response.reply.searchResult.item[index+1]
            .sellingStatus.convertedCurrentPrice.value
          )

        #Assembling a pick to throw into the 'potentials'
        #list from before
        temp = {
          #Current price
          "price": price,

          #How much you potentially flip this for after fees
          #and approximate shipping costs
          "potential_profit": (true_avg*0.9 - 15) - price,

          #The next highest priced item. This item will undercut your flip
          #until it's bought, so be aware
          "next_highest_price": next_highest_price,

          #URL to the item.
          "url": item.viewItemURL,

          #The average price this item is sold for
          "average": true_avg,

          #sample size
          "accuracy": accuracy,

          #the UPC code used
          "upc": upc
        }

        #Heres your chance to deem this item a potential flip or not.
        #If this item doesnt pass all tests, it's passed on.
        #Add additional tests to this array as you wish
        
        tests = [
          #Is there even a worthwhile profit to be made?
          29.99 < temp["potential_profit"], 

          #are there any other items undercutting my flip?
          29.99 < temp["average"] - temp["next_highest_price"],

          #Is this a scammer? The main tell is the too-good-to-be-true profit
          temp["potential_profit"] < temp["price"]*0.6,
        ]

        #Run the tests
        #Add item to potentials if it passes
        if all(tests):
          potentials.append(temp)

    #Sort potentials by the largest potential flips
    newlist = sorted(
      potentials,
      key=lambda k: k['potential_profit']
    ) 

    #Post any found 'potentials' to discord, or at least "heartbeat"
    if len(newlist):    
        print_to_discord("@channel Ebay Picks:\n"+ "\n".join(str(x) for x in newlist))
        print(time.strftime("%I:%M:%S") + " - Picks found")
    else:
        print(time.strftime("%I:%M:%S") + " - No picks yet...")

def alive():
    print_to_discord("ebay bot still alive")

def print_to_discord(message):      
  requests.post(
    config.DISCORD_WEBHOOK,
    data = { "content": message }
  )

#Say we're running, start an initial run of this bot, 
#and schedule it to run every 'x' minutes based on config.INTERVAL
print_to_discord('running')
job()
schedule.every(config.INTERVAL).minutes.do(job)
schedule.every(1).days.do(alive)
while 1:
  schedule.run_pending()
  time.sleep(1)