from boto3 import client as botoclient

import json
import lxml.etree as ET
from io import BytesIO


class MTurk(object):

	"""
	boto3.mturk API Reference:
	http://boto3.readthedocs.io/en/latest/reference/services/mturk.html#MTurk.Client
	"""
	def __init__(self, config_file=None, config_name=None):
		config_file = "./config.json" if config_file is None else config_file
		config_name = "default" if config_name is None else config_name
		with open(config_file, "r") as f:
			config = json.load(f)[config_name]

		self.service_name = "mturk"
		self.region_name = "us-east-1"
		self.aws_access_key_id = config["aws_access_key_id"]
		self.aws_secret_access_key = config["aws_secret_access_key"]
		if config["sandbox"]:
			self.endpoint_url = "https://mturk-requester-sandbox.us-east-1.amazonaws.com"
		else:
			self.endpoint_url = "https://mturk-requester.us-east-1.amazonaws.com"

		self.client = botoclient(
			service_name = self.service_name,
			region_name = self.region_name,
			endpoint_url = self.endpoint_url,
			aws_access_key_id = self.aws_access_key_id,
			aws_secret_access_key = self.aws_secret_access_key,
		)

	def getAccountBalance(self):
		response = self.client.get_account_balance()
		return response["AvailableBalance"]

	def getAssignment(self, id=None):
		response = self.client.get_assignment(
			AssignmentId=id,
		)
		return response["Assignment"]

	def listAssignmentsForHIT(self, id=None):
		response = self.client.list_assignments_for_hit(
			HITId=id,
			MaxResults=100,
		)
		return response["Assignments"]

	def listWorkersWithQualificationType(self, id=None):
		response = self.client.list_workers_with_qualification_type(
			QualificationTypeId=id,
			MaxResults=100,
		)
		return sorted(response["Qualifications"], key=lambda x: x["GrantTime"])

	
	def parseAns(self, assignments):
		ans = {}
		parser = QAXML("QuestionFormAnswers")
		for assignment in assignments:
			kv = parser.getAnswer(assignment["Answer"])
			for k in kv:
				if k in ans.keys():
					ans[k].append(kv[k])
				else:
					ans[k] = [kv[k]]
		return ans



class QAXML(object):

	"""
	Question and Answer Data API Reference:
	http://docs.aws.amazon.com/AWSMechTurk/latest/AWSMturkAPI/ApiReference_QuestionAnswerDataArticle.html
	"""
	def __init__(self, schema):
		self.schema_namespace = {
			"HTMLQuestion": "http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2011-11-11/HTMLQuestion.xsd",
			"ExternalQuestion": "http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd",
			"XHTML": "http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2006-07-14/FormattedContentXHTMLSubset.xsd",
			"QuestionForm": "http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2005-10-01/QuestionForm.xsd",
			"QuestionFormAnswers": "http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2005-10-01/QuestionFormAnswers.xsd",
			"AnswerKey": "http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2005-10-01/AnswerKey.xsd",
		}
		self.schema = schema
		self.xml = ET.Element(self.schema, {"xmlns": self.schema_namespace[self.schema]})


	"""
	title: string, text: string, html: HTML string
	"""
	def addOverview(self, title=None, text=None, html=None):
		assert self.schema == "QuestionForm"
		overview = ET.SubElement(self.xml, "Overview")
		if title is not None:
			ET.SubElement(overview, "Title").text = title
		if text is not None:
			ET.SubElement(overview, "Text").text = text
		if html is not None:
			ET.SubElement(overview, "FormattedContent").text = ET.CDATA(html)


	"""
	qslst = [{
		qid:       string,          # question id
		name:      string,          # display name
		content:   HTML string,     # question content
		selection: list of string,  # list of answer selections
	}, ...]
	"""
	def addQuestionList(self, qslst):
		assert self.schema == "QuestionForm"
		for qs in qslst:
			question = ET.SubElement(self.xml, "Question")
			ET.SubElement(question, "QuestionIdentifier").text = str(qs["qid"])
			ET.SubElement(question, "DisplayName").text = str(qs["name"])
			ET.SubElement(question, "IsRequired").text = "true"
			qcontent = ET.SubElement(question, "QuestionContent")
			ET.SubElement(qcontent, "FormattedContent").text = ET.CDATA(qs["content"])
			answer = ET.SubElement(question, "AnswerSpecification")
			selectans = ET.SubElement(answer, "SelectionAnswer")
			ET.SubElement(selectans, "StyleSuggestion").text = "radiobutton"
			selections = ET.SubElement(selectans, "Selections")
			for idx, each in enumerate(qs["selection"]):
				selection = ET.SubElement(selections, "Selection")
				ET.SubElement(selection, "SelectionIdentifier").text = str(idx + 1)
				ET.SubElement(selection, "FormattedContent").text = ET.CDATA(str(each))


	"""
	anslst = [{
		qid:    string,          # question id
		sid:    list of string,  # list of selection id
		score:  int,             # answer score
	}, ...]
	"""
	def addAnswerList(self, anslst):
		assert self.schema == "AnswerKey"
		scoresum = 0
		for ans in anslst:
			question = ET.SubElement(self.xml, "Question")
			ET.SubElement(question, "QuestionIdentifier").text = str(ans["qid"])
			ansopt = ET.SubElement(question, "AnswerOption")
			for each in ans["sid"]:
				ET.SubElement(ansopt, "SelectionIdentifier").text = str(each)
			ET.SubElement(ansopt, "AnswerScore").text = str(ans["score"])
			scoresum += int(ans["score"])
		qualification = ET.SubElement(self.xml, "QualificationValueMapping")
		percentage = ET.SubElement(qualification, "PercentageMapping")
		ET.SubElement(percentage, "MaximumSummedScore").text = str(scoresum)


	def getAnswer(self, ansxml):
		ansxml = str.encode(ansxml)
		assert self.schema == "QuestionFormAnswers"
		assert ET.XML(ansxml).tag == "{{{}}}{}".format(self.schema_namespace[self.schema], self.schema)
		ans = {}
		for _, element in ET.iterparse(
			BytesIO(ansxml),
			tag = "{{{}}}{}".format(self.schema_namespace[self.schema], "Answer")
		):
			identifier = "{{{}}}{}".format(self.schema_namespace[self.schema], "QuestionIdentifier")
			ans[element.findtext(identifier)] = element[1].text
			element.clear()
		return ans


	def toString(self):
		return ET.tostring(self.xml).decode("utf-8")


