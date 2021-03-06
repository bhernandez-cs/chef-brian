from __future__ import print_function # to use print starting from Python 2
import sys  # for error handling in the database
import unirest, json
import boto3 # to use Amazon services like DynamoDB
import decimal
from bs4 import BeautifulSoup # for web scraping
import re # for string splitting

class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert a DynamoDB item to JSON."""
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)


#sets up the DynamoDB client to create tables and the resource to work with those tables
#I use my secret security credentials, but you'll have to generate and use your own
dynamodbClient = boto3.client('dynamodb', region_name='us-east-1', aws_access_key_id = '<something secret>', aws_secret_access_key = '<something secret>',)
dynamodbResource = boto3.resource('dynamodb', region_name='us-east-1', aws_access_key_id = '<something secret>', aws_secret_access_key = '<something secret>',)
TABLE_NAME_FOR_ANY_ACCOUNT = "chefBrianData"

# --------------- Request handler ------------------
def lambdaHandler(event, context):
    print("event.session.application.applicationId=" +
          event['session']['application']['applicationId'])

    #check if the application id matches the session id
    if (event['session']['application']['applicationId'] != "<something secret"):
        raise ValueError("Invalid Application ID")

    #launch different function depending on type of request
    if event['request']['type'] == "LaunchRequest":
        return onLaunch(event['request'], event['session']) #request without an intent -> welcome message
    elif event['request']['type'] == "IntentRequest":
        return onIntent(event['request'], event['session']) #request with an intent -> intent handler
    elif event['request']['type'] == "SessionEndedRequest":
        return onSessionEnded(event['request'], event['session']) #request to end the session -> session ender

# --------------- Request Handles ------------------
def onLaunch(launch_request, session):
    """ Called when the user launches the skill without specifying what they want"""
    return getWelcomeResponse(session)

def onIntent(intent_request, session):
    """ Called when the user specifies an intent for this skill """

    #attempt to create a recipe data table before going through any intent
    createTable()

    intent = intent_request['intent']
    intent_name = intent_request['intent']['name']

    #intent to get the recipe asked for
    if intent_name == "getRecipeIntent":
        return getRecipe(intent, session)
    #intent to have ingredients read out
    elif intent_name == "readIngredientsIntent":
        return readIngredients(intent, session)
    #intent to start reading the recipe instructions
    elif intent_name == "startRecipeIntent":
        return startRecipe(intent, session)
    #intent to advance to the next step of the instructions
    elif intent_name == "nextStepIntent":
        return nextStep(intent, session)
    #intent to repeat the current step
    elif intent_name == "repeatStepIntent":
        return repeatStep(intent, session)
    #intent to go back to the previous step
    elif intent_name == "previousStepIntent":
        return previousStep(intent, session)
    #intent to load recipe data
    elif intent_name == "loadRecipeIntent":
            return loadRecipe(intent, session)
    #help intent
    elif intent_name == "AMAZON.HelpIntent":
        return helpResponse(intent, session)
    #quit intents
    elif intent_name == "AMAZON.CancelIntent" or intent_name == "AMAZON.StopIntent":
        return sessionEndRequestHandle()
    else:
        raise ValueError("Invalid intent")

def onSessionEnded(session_ended_request, session):
    """ Called when the user ends the session. Is not called when the skill returns should_end_session=true"""
    print("on_session_ended requestId=" + session_ended_request['requestId'] + ", sessionId=" + session['sessionId'])


# --------------- Functions for all of the intents ------------------
def getWelcomeResponse(session):
    """Return the welcome response when no intent is specified"""

    try:
        session_attributes = session["attributes"]
    except:
        session_attributes = {}
        session_attributes["currentStep"] = -1
        session_attributes["recipeName"] = ""
        session_attributes["recipeInstructions"] = []
        session_attributes["recipeFound"] = False
        session_attributes["recipeIngredients"] = []

        card_title = "Time to Cook"
        speech_output = "Time to cook!" + " First, let's tell mini chef what you want to make."
        text_output = "Time to cook!" + " First, let's tell mini chef what you want to make."
        reprompt_text = "You can ask mini chef to find a recipe by saying 'Let's make chocolate chip cookies' for example. To hear the full list of commands just say 'help'."
        should_end_session = False
    else:
        card_title = "Welcome Back"
        speech_output = "Welcome back. To continue cooking from where you stopped just say 'continue cooking'."
        text_output = "To continue cooking from where you stopped just say 'continue cooking'."
        reprompt_text = "To hear the full list of commands just say 'help'."
        should_end_session = False

    return buildResponse(session_attributes, buildSpeechResponse(
        card_title, speech_output, text_output, reprompt_text, should_end_session))

def helpResponse(intent, session):
    """Return the help response"""

    try:
        session_attributes = session["attributes"]
    except:
        session_attributes = {}
        session_attributes["currentStep"] = -1
        session_attributes["recipeName"] = ""
        session_attributes["recipeInstructions"] = []
        session_attributes["recipeFound"] = False
        session_attributes["recipeIngredients"] = []

    card_title = "mini chef - Help"
    speech_output = "Hi, I'm mini chef! Here are some things you can say: 'let's make chocolate chip cookies', 'ingredients', 'instructions, next', 'go back', 'repeat', or continue cooking'. Lastly, you can also say stop if you're done cooking. Now, what would you like to do?"
    text_output = "Here are some things you can say: 'let's make chocolate chip cookies', 'ingredients', 'instructions, next' or 'go on', 'previous' or 'go back', 'repeat' or 'what', or continue cooking'. Lastly, you can also say stop if you're done cooking."
    reprompt_text = ""
    should_end_session = False
    return buildResponse(session_attributes, buildSpeechResponse(
        card_title, speech_output, text_output, reprompt_text, should_end_session))

def sessionEndRequestHandle():
    """Return the end session response for when a user escapes the session"""

    card_title = "Voila, All Done"
    speech_output = "I hope cooking with me was fun. " + "Bon appetit!"
    text_output = "I hope cooking with me was fun. " + "Bon appetit!"
    # Setting this to true ends the session and exits the skill.
    should_end_session = True
    return buildResponse({}, buildSpeechResponse(
        card_title, speech_output, text_output, None, should_end_session))

def getRecipe(intent, session):
    """Return the most relevant recipe"""

    card_title = "mini chef Could Not Find a Recipe"
    session_attributes = {}
    should_end_session = False

    #if the recipe list exists in the slots (slots list is specified in Amazon developer console)
    if 'Recipe' in intent['slots']:
        try:
            recipeSearchQuery = intent['slots']['Recipe']['value'] #store the name of the recipe
        except:
            speech_output = "What was that?"
            text_output = "What was that?"
            reprompt_text = "What was that?"
            should_end_session = False
            return buildResponse(session_attributes, buildSpeechResponse(card_title, speech_output, text_output, reprompt_text, should_end_session))
        else:
            #scrape Epicurious search page for the first (they're sorted by relevance) recipe
            searchUrl = "http://www.epicurious.com/search/" + recipeSearchQuery + "?content=recipe"
            searchResponse = unirest.get(searchUrl)
            searchData = searchResponse.body
            searchSource = BeautifulSoup(searchData, 'html.parser') #the data from the response is just the HTML of the page, so to parse it we use Soup

            try:
                recipe = searchSource.find('a', { "class" : "view-complete-item" }) #we find the first '<a>' HTML tag (link) with a class of recipeLnk
                recipeName = recipe.get('title') #extract its text
            except:
                speech_output = "I'm sorry, but mini chef doesn't have a recipe for " + recipeSearchQuery + "."
                text_output = "I'm sorry, but mini chef doesn't have a recipe for " + recipeSearchQuery + "."
                reprompt_text = "I'm sorry, but mini chef doesn't have a recipe for " + recipeSearchQuery + "."
                should_end_session = True
            else:
                recipeLink = recipe.get('href') #and the actual link

                #we use the recipe link from the search to get the ingredients and instructions of the first recipe
                recipeGetUrl = "http://www.epicurious.com" + recipeLink
                recipeResponse = unirest.get(recipeGetUrl)
                recipeData = recipeResponse.body
                recipeSource = BeautifulSoup(recipeData, 'html.parser')

                recipeIngredients = []
                recipeInstructions = []
                #for every <li> (list item) of class ingredient add its text to the list
                for ingredient in recipeSource.find_all('li', { "class" : "ingredient" }):
                    recipeIngredients.append(ingredient.get_text() + ". ")
                #for every <li> (list item) of class preparation-step add its text to the list
                for step in recipeSource.find_all('li', { "class" : "preparation-step" }):
                    stepText = step.get_text()
                    stepText = stepText.strip() #strip the text of unnecessary spaces
                    stepSplit = re.split('[.](?=\s)', stepText) #split the string only if a period is followed by a space (ex: not 1.1)
                    for smallStep in stepSplit:
                        if len(smallStep) >= 4: #if the length of the step is larger than 4 character (i.e. not something like 1.) add it to the list
                            recipeInstructions.append(smallStep)

                #set the session attributes and card title for the companion app
                session_attributes["recipeName"] = recipeName
                card_title = "Ingredients for " + recipeName
                session_attributes["recipeFound"] = True
                session_attributes["recipeIngredients"] = recipeIngredients
                session_attributes["recipeInstructions"] = recipeInstructions
                session_attributes["currentStep"] = -1

                #we save the recipe data in the table when we get it
                storeRecipeData(session["user"]["userId"], recipeName, recipeIngredients, recipeInstructions, 0)

                speech_output = "mini chef just found a delicious " + recipeName+ " recipe for us to try. I sent the ingredients to the Alexa companion app. " + "Would you like me to read them or jump straight to the instructions?"
                text_output = "Ingredients:\n"
                for ingredient in recipeIngredients:
                    text_output = text_output + ingredient + "\n"
                reprompt_text = "To hear the ingredients just say 'ingredients'. To skip straight to the instructions say 'instructions'."
    else:
        speech_output = "I'm sorry, but mini chef doesn't have a recipe for " + recipeSearchQuery + "."
        text_output = "I'm sorry, but mini chef doesn't have a recipe for " + recipeSearchQuery + "."
        reprompt_text = "I'm sorry, but mini chef doesn't have a recipe for " + recipeSearchQuery + "."
        should_end_session = True
    return buildResponse(session_attributes, buildSpeechResponse(
        card_title, speech_output, text_output, reprompt_text, should_end_session))

def readIngredients(intent, session):
    """Read the ingredients list aloud"""

    try:
        session_attributes = session["attributes"]
    except:
        session_attributes = {}
        should_end_session = True
        card_title = "We Need Something to Cook First"
        speech_output = "We need something to cook first."
        text_output = "You can start cooking a recipe by saying 'Alexa, let's make chocolate chip cookies for example."
        reprompt_text = "What was that?"
    else:
        card_title = "Ingredients for " + session["attributes"]["recipeName"]

        should_end_session = False
        speech_output = ""
        ingredientsList = session["attributes"]["recipeIngredients"]

        if session["attributes"]["recipeFound"] == True:
            #we save the recipe data in every intent actually just for safety, so no matter what happens, it's always saved
            storeRecipeData(session["user"]["userId"], session["attributes"]["recipeName"], ingredientsList, session["attributes"]["recipeInstructions"], 0)

            for ingredient in ingredientsList:
                speech_output += ingredient
            speech_output += ". Would you like me to repeat the ingredients or go to the instructions?"
            text_output = ""
            reprompt_text = "Say 'instructions' when you're ready to start cooking."
        else:
            speech_output = "I don't understand what you're saying, bro."
            text_output = "I don't understand what you're saying, bro."
            reprompt_text = "I don't understand what you're saying, bro."
    return buildResponse(session_attributes, buildSpeechResponse(
        card_title, speech_output, text_output, reprompt_text, should_end_session))

def startRecipe(intent, session):
    """Start reading the recipe instructions"""
    try:
        session_attributes = session["attributes"]
    except:
        session_attributes = {}
        should_end_session = True
        card_title = "We Need Something to Cook First"
        speech_output = "We need something to cook first."
        text_output = "You can start cooking a recipe by saying 'Alexa, let's make chocolate chip cookies for example."
        reprompt_text = "What was that?"
    else:
        card_title = session["attributes"]["recipeName"]

        #only attempt to read the recipe if it was already found, otherwise prompt to first choose a recipe to make
        if session["attributes"]["recipeFound"] == True:
            recipeText = session["attributes"]["recipeInstructions"]
            if recipeText:
                should_end_session = False
                session_attributes["currentStep"] = 0
                currentStep = session_attributes["currentStep"]
                storeRecipeData(session["user"]["userId"], session["attributes"]["recipeName"], session["attributes"]["recipeIngredients"], recipeText, currentStep)

                speech_output = "Let's start cooking! "+ recipeText[currentStep]
                speech_output += ". Would you like me to repeat this step or go to the next one?"
                text_output = recipeText[currentStep]
                reprompt_text = "Just say 'next' to go to the next step."
            else:
                speech_output = "There are no instructions for this recipe."
                text_output = "There are no instructions for this recipe."
                reprompt_text = "There are no instructions for this recipe."
        else:
            should_end_session = True
            card_title = "We Need Something to Cook First"
            speech_output = "We need something to cook first."
            text_output = "You can start cooking a recipe by saying 'Alexa, let's make chocolate chip cookies for example."
            reprompt_text = "What was that?"

    return buildResponse(session_attributes, buildSpeechResponse(
        card_title, speech_output, text_output, reprompt_text, should_end_session))

def nextStep(intent, session):
    """Go to the next step in the recipe instructions"""
    try:
        session_attributes = session["attributes"]
    except:
        session_attributes = {}
        should_end_session = True
        card_title = "We Need Something to Cook First"
        speech_output = "We need something to cook first."
        text_output = "You can start cooking a recipe by saying 'Alexa, let's make chocolate chip cookies for example."
        reprompt_text = "What was that?"
    else:
        should_end_session = False
        recipeFound = session["attributes"]["recipeFound"]

        recipeText = session["attributes"]["recipeInstructions"]
        currentStep = session["attributes"]["currentStep"]
        currentStep += 1 #increment a current step variable by 1
        card_title = "Step " + `currentStep + 1`

        if currentStep > 0 and currentStep < len(recipeText):

            session_attributes["currentStep"] = currentStep #save the current step to the session attributes
            storeRecipeData(session["user"]["userId"], session["attributes"]["recipeName"], session["attributes"]["recipeIngredients"], recipeText, currentStep)

            speech_output = recipeText[currentStep]
            speech_output += ". Would you like me to repeat this step, go back to the previous one or go to the next one?"
            text_output = recipeText[currentStep]
            reprompt_text = "Just say 'next' to go to the next step."

        else:
            if currentStep <= 0:
                should_end_session = True
                card_title = "We Need Something to Cook First"
                speech_output = "We need something to cook first."
                text_output = "You can start cooking a recipe by saying 'Alexa, let's make chocolate chip cookies for example."
                reprompt_text = "What was that?"
            elif currentStep >= len(recipeText) and len(recipeText) > 0:
                card_title = "Finished!"
                should_end_session = True
                speech_output = "All done. Enjoy your meal."
                text_output = "All done. Enjoy your meal."
                reprompt_text = "All done. Enjoy your meal."

    return buildResponse(session_attributes, buildSpeechResponse(
        card_title, speech_output, text_output, reprompt_text, should_end_session))

def repeatStep(intent, session):
    """Repeat the current step (don't increment current step)"""

    try:
        session_attributes = session["attributes"]
    except:
        session_attributes = {}
        should_end_session = True
        card_title = "We Need Something to Cook First"
        speech_output = "We need something to cook first."
        text_output = "You can start cooking a recipe by saying 'Alexa, let's make chocolate chip cookies for example."
        reprompt_text = "What was that?"
    else:
        should_end_session = False

        recipeText = session["attributes"]["recipeInstructions"]
        currentStep = session["attributes"]["currentStep"]
        card_title = "Step " + `currentStep + 1`

        if currentStep >= 0 and currentStep < len(recipeText):

            session_attributes["currentStep"] = currentStep
            storeRecipeData(session["user"]["userId"], session["attributes"]["recipeName"], session["attributes"]["recipeIngredients"], recipeText, currentStep)

            speech_output = recipeText[currentStep]
            speech_output += ". Would you like me to repeat this step or go to the next one?"
            text_output = recipeText[currentStep]
            reprompt_text = "Just say 'next' to go to the next step."

        else:
            if currentStep < 0:
                should_end_session = True
                card_title = "We Need Something to Cook First"
                speech_output = "We need something to cook first."
                text_output = "You can start cooking a recipe by saying 'Alexa, let's make chocolate chip cookies for example."
                reprompt_text = "What was that?"
            elif currentStep >= len(recipeText) and len(recipeText) > 0:
                card_title = "Finished!"
                should_end_session = True
                speech_output = "All done. Enjoy your meal."
                text_output = "All done. Enjoy your meal."
                reprompt_text = "All done. Enjoy your meal."

    return buildResponse(session_attributes, buildSpeechResponse(
        card_title, speech_output, text_output, reprompt_text, should_end_session))

def previousStep(intent, session):
    """Read the previous step of the recipe instructions"""

    try:
        session_attributes = session["attributes"]
    except:
        session_attributes = {}
        should_end_session = True
        card_title = "We Need Something to Cook First"
        speech_output = "We need something to cook first."
        text_output = "You can start cooking a recipe by saying 'Alexa, let's make chocolate chip cookies for example."
        reprompt_text = "What was that?"
    else:
        should_end_session = False

        recipeText = session["attributes"]["recipeInstructions"]
        currentStep = session["attributes"]["currentStep"]
        currentStep -= 1  #decrement current steo by 1
        card_title = "Step " + `currentStep + 1`

        if currentStep >= 0 and currentStep < len(recipeText):

            session_attributes["currentStep"] = currentStep
            storeRecipeData(session["user"]["userId"], session["attributes"]["recipeName"], session["attributes"]["recipeIngredients"], recipeText, currentStep)

            speech_output = recipeText[currentStep]
            speech_output += ". Would you like me to repeat this step or go to the next one?"
            text_output = recipeText[currentStep]
            reprompt_text = "Just say 'next' to go to the next step."

        else:
            if currentStep < 0:
                if session["attributes"]["recipeFound"] == True:
                    currentStep += 1
                    session_attributes["currentStep"] = currentStep
                    card_title = "Step " + `currentStep + 1`
                    should_end_session = False
                    speech_output = recipeText[currentStep]
                    text_output = recipeText[currentStep]
                    reprompt_text = ""
                else:
                    should_end_session = True
                    card_title = "We Need Something to Cook First"
                    speech_output = "We need something to cook first."
                    text_output = "You can start cooking a recipe by saying 'Alexa, let's make chocolate chip cookies for example."
                    reprompt_text = "What was that?"
            elif currentStep >= len(recipeText) and len(recipeText) > 0:
                card_title = "Finished!"
                should_end_session = True
                speech_output = "All done. Enjoy your meal."
                text_output = "All done. Enjoy your meal."
                reprompt_text = "All done. Enjoy your meal."

    return buildResponse(session_attributes, buildSpeechResponse(
        card_title, speech_output, text_output, reprompt_text, should_end_session))

def loadRecipe(intent, session):
    """Load the recipe data"""

    session_attributes = {}

    #retrieve the recipe data from the table
    recipe = loadRecipeData(session["user"]["userId"])
    #if it's not empty, set the session attributes to it and build a response to the intent
    if recipe:
        session_attributes["currentStep"] = recipe["currentStep"]
        session_attributes["recipeName"] = recipe["recipeName"]
        session_attributes["recipeInstructions"] = recipe["recipeInstructions"]
        session_attributes["recipeFound"] = True
        session_attributes["recipeIngredients"] = recipe["recipeIngredients"]

        card_title = recipe["recipeName"] + " recipe found"
        recipeText = recipe["recipeInstructions"]
        speech_output = "We stopped on step " + str(recipe["currentStep"]+1) + ". " + recipeText[recipe["currentStep"]]
        speech_output += ". Would you like me to repeat this step or go to the next one?"
        text_output = "We stopped on step " + str(recipe["currentStep"]+1) + ". " + recipeText[recipe["currentStep"]]
        reprompt_text = "Just say 'next' to go to the next step."
        should_end_session = False
    #otherwise set the sesison attributes to defaults and say that no recipe data could be found
    else:
        session_attributes["currentStep"] = -1
        session_attributes["recipeName"] = ""
        session_attributes["recipeInstructions"] = []
        session_attributes["recipeFound"] = False
        session_attributes["recipeIngredients"] = []

        card_title = "Couldn't find a saved recipe"
        should_end_session = True
        speech_output = "It seems like I couldn't find a recipe in progress. Say 'let's make' and the name of a dish to start cooking it."
        text_output = "It seems like I couldn't find a recipe in progress."
        reprompt_text = ""

    return buildResponse(session_attributes, buildSpeechResponse(
        card_title, speech_output, text_output, reprompt_text, should_end_session))


# --------------- Helpers that build all of the responses ----------------------
def buildSpeechResponse(title, output, text_output, reprompt_text, should_end_session):
    """Build the json for the speech response for Alexa"""
    return {
        'outputSpeech': {
            'type': 'PlainText',
            'text': output
        },
        'card': {
            'type': 'Simple',
            'title': title,
            'content': text_output
        },
        'reprompt': {
            'outputSpeech': {
                'type': 'PlainText',
                'text': reprompt_text
            }
        },
        'shouldEndSession': should_end_session#
    }

def buildResponse(session_attributes, speechlet_response):
    """Build the entire json response including passing in the session attributes"""
    return {
        'version': '1.0',
        'sessionAttributes': session_attributes,
        'response': speechlet_response
    }


#-------------------Functions for DynamoDB table operations---------------------
def createTable():
    #try to get the info for an existing table
    try:
        existingTable = dynamodbClient.describe_table(TableName = TABLE_NAME_FOR_ANY_ACCOUNT)
    #but if there's an exception create a new table
    except:
        newTable = dynamodbClient.create_table(
            TableName = TABLE_NAME_FOR_ANY_ACCOUNT,
            KeySchema = [ #every table needs a key, which is a unique value for every item in the table
                {
                    'AttributeName': 'userId',
                    'KeyType': 'HASH'
                }
            ],
            AttributeDefinitions = [
                {
                    'AttributeName': 'userId',
                    'AttributeType': 'S'
                },
            ],
            ProvisionedThroughput = {  #some advanced bullshit
                'ReadCapacityUnits': 10,
                'WriteCapacityUnits': 10
            }
        )

def storeRecipeData(userId, name, ingredients, instructions, step):
    #try to save the recipe data to the table
    try:
        table = dynamodbResource.Table(TABLE_NAME_FOR_ANY_ACCOUNT)
        tableWithRecipe = table.put_item( #we put all the values into a dictionary, which acts as our item
            Item = {
                'userId': userId,
                'recipeFound': 'True',
                'recipeName': name,
                'recipeIngredients': ingredients,
                'recipeInstructions': instructions,
                'currentStep': step
            }
        )
    except: #print the exception if saving fails for some reason (not ever supposed to)
        e = sys.exc_info()[0]
        print(e)

def loadRecipeData(userId):
    try: #try to load the recipe corresponding to the user of this Amazon device
        table = dynamodbResource.Table(TABLE_NAME_FOR_ANY_ACCOUNT)
        recipeGet = table.get_item(
            Key={    #we get the item by its key, which is the user id of the device (every device gets a user id)
                'userId': userId
            }
        )
    except:
        e = sys.exc_info()[0]
        print(e)
    else:
        item = recipeGet['Item']   #if saving works we get the item from the given dictionary
        recipeJSON = json.dumps(item, indent=4, cls=DecimalEncoder)  #make it a string
        return json.loads(recipeJSON) #make it JSON
