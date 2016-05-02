''' 0. intro

notes:
- this is run via cron every minute
- this is hosted on a digitalocean server 
- warnings are suppressed because apparently i was using something
  deprecated, and fixing that was not a priority
- the number of emails in the past hour (both sent and received)
  functions only work sometimes
  - i have no idea why, though i suspect it might have something to
    do with my hard coding in ME, ALSO_ME, and THIS_TOO_IS_ME...
  - but received worked before??? this is also quite sad, because emails
    received is my feature with the highest coefficient
  - sent never worked
- this code is super time inefficient. there's more than one function
  that works basically by going through each email and asking, "is this
  [some quality that only applied to a small percentage of emails]?"
  - i could fix this by preprocessing a lot more, but
    - getting this working was a higher priority
    - that would be space inefficient (bc i'd probably use hella
      hashtables)
      - though it would probably still be worth it
- learned a lot! =D
'''
#!/usr/bin/env python
import imaplib, email, getpass, datetime, pytz, smtplib, math, numpy, time
from mailbot import MailBot, register, Callback
from email.utils import getaddresses
from dateutil import parser, relativedelta
from sklearn.linear_model import LinearRegression
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# this needed to be done
import warnings
warnings.filterwarnings("ignore")

''' 1. logging into email

Thanks:
https://flowingdata.com/2014/05/07/downloading-your-email-metadata/
Chloe for pointing out on Slack that I needed port 993 and SSL set to True.
'''

PORT = 993  # port number, usually 143 or 993 if ssl is enabled
SSL = True
ME = '"george, lily" <lily_george@brown.edu>'
ALSO_ME = 'lily_george@brown.edu'
THIS_TOO_IS_ME = '"lily george" <lily_george@brown.edu>'
SECONDS_IN_AN_HR = 3600

# Email settings
HOSTNAME = 'imap.gmail.com'
SMTP_HOSTNAME = 'smtp.gmail.com'
USERNAME = 'lily_george@brown.edu'
PASSWORD = getpass.getpass()
MAILBOX = '[Gmail]/All Mail'

# Connection
conn = imaplib.IMAP4_SSL(HOSTNAME)
(retcode, capabilities) = conn.login(USERNAME, PASSWORD)

''' 2. retrieving all email

Thanks:
https://flowingdata.com/2014/05/07/downloading-your-email-metadata/
http://www.secnetix.de/olli/Python/list_comprehensions.hawk
Emma for suggesting using a try-catch
'''

# Specify email folder
conn.select(MAILBOX, readonly=True)   # Set readOnly to True so that emails aren't marked as read

# Search for email ids between dates specified
result, data = conn.uid('search', None, 'ALL')
uids = data[0].split()

# Download headers
result, data = conn.uid('fetch', ','.join(uids), '(BODY[HEADER.FIELDS (MESSAGE-ID FROM TO DATE SUBJECT IN-REPLY-TO DELIVERED-TO)])')

# a list that will hold dictionaries holding message data
all_email = []

# WRITE THE DOCS FOR THIS LATER
def get_email(raw_data):
    
    # Parse data and spit out info
    for i in range(0, len(data)):

        # a dictionary holding message data
        # -> key is a string, like "message-id" or "date"
        # -> value is either a string or a struct_time or a list of strings
        # -> -> I know variable value types is bad, but... it's probably fine...
        msg_data = {}

        # If the current item is _not_ an email header
        if len(data[i]) != 2:
            continue

        # Okay, it's an email header.
        # Get all the email data.
        msg = email.message_from_string(data[i][1])

        try:
             # add the stuff to the dictionary
            msg_data['message-id'] = msg.get_all('message-id', [])[0]
            msg_data['from'] = [x.lower() for x in msg.get_all('from', [])]
            msg_data['to'] = [x.lower() for x in msg.get_all('delivered-to', [])]
            msg_data['in-reply-to'] = msg.get_all('in-reply-to', [])
            msg_data['date'] = parser.parse(msg.get_all('date', None)[0])
            if msg.get_all('subject', []) != []:
                msg_data['subject'] = msg.get_all('subject', [])[0]
            else:
                msg_data['subject'] = '(no subject)'
                
            all_email.append(msg_data)
            
        except (ValueError, IndexError, TypeError):
            print ":/"

get_email(data)

''' 3. make the important information easily accessible '''

# add_messages_to_dict_by_id : dict -> dict
# input : messages - all_email (my janky list of dicts), basically
# output : a dict where the key is the msg-id and value is information
#          about that email (to, from, cc, etc)
def add_messages_to_dict_by_id(messages):
    toReturn = {}
    for message in messages:
        message_id = message['message-id']
        toReturn[str(message_id)] = message
    return toReturn

# dictionary where key is msg-id and vals are dict of everything else
id_dict = add_messages_to_dict_by_id(all_email)

# make_dict_by_inreplyto : list dict -> dict
# input : messages - a list of all messages
#         messages_by_id - dict where key is message id and val
#                          is other info about the message
# output : dict where key is a person and value is a list of all messages
#          from that person that I have replied to
def make_dict_by_inreplyto(messages, messages_by_id):
    toReturn = {}
    for message in messages:
        if message['in-reply-to'] != []:
            
            id_of_inreplyto_msg = message['in-reply-to'][0]

            if id_of_inreplyto_msg in messages_by_id:

                replyto_msg_dict = messages_by_id[id_of_inreplyto_msg]
                fromlist = replyto_msg_dict['from']

                # there is an in-reply-to person
                if fromlist[0] != []:

                    # the person is already in the toReturn hashtable
                    if fromlist[0] in toReturn:
                        toReturn[fromlist[0]].append(id_of_inreplyto_msg)

                    # they are not already there
                    else:
                        toReturn[fromlist[0]] = [id_of_inreplyto_msg]

    return toReturn

# make dictionary of everyone I've ever replied to
replyto_dict = make_dict_by_inreplyto(all_email, id_dict)

''' 4. writing functions to get the features

Thanks:
Jessica for explaining to me that the labels are not email addresses, but
instead we should make all our features after getting an email and knowing who
we're talking to.
Emma for suggesting I use the .total_seconds() function.
'''

# find_response_times : str -> listof(float)
# input : sender - a str with an email
#         messages - all my email
# output : a list of times I've taken to respond to them
def find_response_times(sender, messages):
    
    times_for_sender = []
    for message in messages:
        from_address = message['from'][0]

        # if i'm replying to someone
        if message['in-reply-to'] != []:

            email_im_responding_to = message['in-reply-to'][0]

            # you can't find the email (probably a deletion)
            if not (email_im_responding_to in id_dict):
                continue

            # email is in id_dict
            else:
                if email_im_responding_to in replyto_dict[sender]:

                    all_emails_to_this_person = replyto_dict[sender]
                    my_message_time = message['date'].replace(tzinfo=pytz.timezone('UTC'))
                    their_message_time = id_dict[email_im_responding_to]['date'].replace(tzinfo=pytz.timezone('UTC'))
                    time_diff = (my_message_time - their_message_time).total_seconds()    
                    times_for_sender.append(time_diff)
                        
    return times_for_sender

# mean_time_for_person : str listof(dict) -> float
# input : sender - str holding email of sender
#         messages - all emails
# output : mean response time for that person
def mean_time_for_person(response_times):
    return numpy.mean(response_times)

# mean_time_for_person : str listof(dict) -> float
# input : sender - str holding email of sender
#         messages - all emails
# output : median response time for that person
def median_time_for_person(response_times):
    return numpy.median(response_times)

# make_all_times_for_everyone : listof(dict) -> listof(float)
# input : messages - all the emails ever
# output : a list of all reply times
def make_all_times_for_everyone(messages):
    times_per_person = []
    for key in replyto_dict:
        times_per_person.append(find_response_times(key, messages))

    toReturn = []
    for person_times in times_per_person:
        for time in person_times:
            toReturn.append(time)

    return toReturn

all_times_for_everyone = make_all_times_for_everyone(all_email)

median_response_times = numpy.median(all_times_for_everyone)
mean_response_times = numpy.mean(all_times_for_everyone)

# num_emails_sent_in_prev_hr : str -> listof(int)
# input : email_id - an email i have received
# output : the number of emails I sent in the hour prior to receiving that email
def num_emails_sent_in_prev_hr(email_id, messages):
    emails_this_hr = 1
    for i in range(0, len(messages) - 1):
        if messages[i]['message-id'] == email_id:
            k = i
            while ((messages[i]['date'].replace(tzinfo=pytz.timezone('UTC')) -\
                   messages[k]['date'].replace(tzinfo=pytz.timezone('UTC'))).total_seconds()\
                
                   <= SECONDS_IN_AN_HR) and k >= 0:

                if (messages[k]['from'][0] == ME or messages[k]['from'][0] == ALSO_ME or\
                 messages[k]['from'][0] == THIS_TOO_IS_ME):
                    emails_this_hr+=1
                k-=1
    return emails_this_hr

prev_hr_sent = num_emails_sent_in_prev_hr(all_email[len(all_email) - 1]['message-id'], all_email)

# num_emails_received_in_prev_hr : str -> listof(int)
# input : email_id - an email i have received
# output : the number of emails I sent in the hour prior to receiving that email
def num_emails_received_in_prev_hr(email_id, messages):
    emails_this_hr = 1
    for i in range(0, len(messages) - 1):
        if messages[i]['message-id'] == email_id:
            k = i
            while ((messages[i]['date'].replace(tzinfo=pytz.timezone('UTC')) -\
                   messages[k]['date'].replace(tzinfo=pytz.timezone('UTC'))).total_seconds()\
                   <= SECONDS_IN_AN_HR) and k >= 0:
                emails_this_hr+=1
                k-=1
    return emails_this_hr - prev_hr_sent

prev_hr_received = num_emails_received_in_prev_hr(all_email[len(all_email) - 1]['message-id'], all_email)

# make_feature_list : str listof(float) listof(dict) -> listof(listof(number))
# input : sender - str with email
#         response_times - list of times i've taken to respond to that sender
#         messages - all the messages ever
def make_feature_list(sender, response_times, messages):
    emails_to_sender = replyto_dict[sender]
    all_features = []
    for email_id in emails_to_sender:
        this_feature = make_data_point(id_dict[email_id], response_times)
        all_features.append(this_feature)
    return all_features

# make_data_point : dict -> listof(float)
# input : new_email - dict holding info about the new email i just received
# output : go through the 
def make_data_point(new_email, response_times):    
    seconds_since_midnight = (new_email['date'] - new_email['date'].replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
    this_person_median_response_time = median_time_for_person(response_times)
    num_emails_received_in_prev_hr(new_email['message-id'], all_email)
    return [this_person_median_response_time, prev_hr_sent, prev_hr_received, seconds_since_midnight]

''' 5. writing the response '''

# email_to_respond_to : dict -> str
# input : the email we need to respond to, as a dict
# output : A string, the email you want to send
def write_message(email_to_respond_to):

    tR = "Hi friend!\n"

    tR = tR + "This is an automatically generated email written to let you know when to expect a reply from Lily."
    tR = tR + " It is for a class assignment and should not be taken too seriously. :) \n\n"
    tR = tR + " Here are some statistics on Lily's previous email interactions with you:\n\n"

    person_response_times = find_response_times(email_to_respond_to['from'][0], all_email)

    mean = mean_time_for_person(person_response_times)
    tR = tR + "Mean response time to you (in hrs): " + str(mean / SECONDS_IN_AN_HR) + "\n"

    median = median_time_for_person(person_response_times)
    tR = tR + "Median response time to you (in hrs): " + str(median / SECONDS_IN_AN_HR) + "\n"

    tR = tR + "Mean response time for everyone (in hrs): " + str(mean_response_times / SECONDS_IN_AN_HR) + "\n"
    tR = tR + "Median response time for everyone (in hrs): " + str(median_response_times / SECONDS_IN_AN_HR) + "\n\n"

    tR = tR + "(The following two metrics are a little buggy still, so don't count too much on them!)\n"
    tR = tR + "Number of emails Lily has sent in the previous hour: "
    tR = tR + str(prev_hr_sent) + "\n"
    tR = tR + "Number of emails Lily has received in the previous hour: "
    tR = tR + str(prev_hr_received) + "\n\n"

    # draft the email
    features = make_feature_list(email_to_respond_to['from'][0], person_response_times, all_email)
    labels = person_response_times

    # addresses are data and times are labels
    lin_reg = LinearRegression()
    lin_reg.fit(features, labels)

    email_prediction = lin_reg.predict(make_data_point(email_to_respond_to, person_response_times))
    reply_time_in_hrs = math.ceil(email_prediction / SECONDS_IN_AN_HR)

    tR = tR + "Based on the information listed and a few more data points (for example, the "
    tR = tR + "time of day), I predict that you will receive a reply within " + str(int(reply_time_in_hrs))
    tR = tR + " hours.\n\n"

    tR = tR + "This email was written by a Python script, so if you see any"\
                + " bugs or have any feedback, please let Lily know! :)"

    return tR

''' 6. sending the response

Thanks:
http://www.gossamer-threads.com/lists/python/python/475867
http://mailbot.readthedocs.io/en/latest/#
http://stackoverflow.com/questions/10147455/how-to-send-an-email-with-gmail-as-provider-using-python
Jessica for explaining what "self" was.
'''

class MyCallback(Callback):

    def trigger(self):

        sender = self.message['from'].lower()
        me = self.message['to'].lower()

        if sender in replyto_dict:

            # get the email data
            new_email = {}
            new_email['message-id'] = self.message['message-id']
            new_email['date'] = parser.parse(self.message['date'])
            
            if 'subject' in self.message:
                new_email['subject'] = self.message['subject'].lower()
            else:
                new_email['subject'] = '(no subject)'
            
            if 'in-reply-to' in self.message:
                new_email['in-reply-to'] = [self.message['in-reply-to'].lower()]
            else:
                new_email['in-reply-to'] = []

            new_email['to'] = [me]
            new_email['from'] = [sender]

            msg_body = "\r\n".join([
              "From: " + me,
              "To: " + sender,
              "Subject: " + new_email['subject'],
              "",
              write_message(new_email)
              ])

            s = smtplib.SMTP(SMTP_HOSTNAME)
            s.set_debuglevel(1) 
            s.ehlo() 
            s.starttls() 
            s.ehlo() 
            s.login(USERNAME, PASSWORD)
            s.sendmail(me, sender, msg_body)
            s.close()

        ''' 7. save a draft

        Thanks:
        http://stackoverflow.com/questions/7519135/creating-a-draft-message-in-gmail-using-the-imaplib-in-python
        http://stackoverflow.com/questions/771907/python-how-to-store-a-draft-email-with-bcc-recipients-to-exchange-server-via-im
        http://stackoverflow.com/questions/17874360/python-how-to-parse-the-body-from-a-raw-email-given-that-raw-email-does-not
        '''

        for payload in self.message.get_payload():
            # if payload.is_multipart(): ...
            if 'please' in str(payload) or 'Please' in str(payload) or 'can' \
                    in str(payload) or 'Can' in str(payload):

                message = MIMEMultipart()
                message['Subject'] = self.message['subject'] 
                message['From'] = me
                message['to'] = sender 
                message.attach(MIMEText('On it! :)\n')) 

                conn.append("[Gmail]/Drafts" 
                              ,'' 
                              ,imaplib.Time2Internaldate(time.time()) 
                              ,str(message)) 

            print payload.get_payload()        

# register the callback
register(MyCallback)

mailbot = MailBot(HOSTNAME, USERNAME, PASSWORD, port=PORT, ssl=SSL)

# check the unprocessed messages and trigger the callback
mailbot.process_messages()