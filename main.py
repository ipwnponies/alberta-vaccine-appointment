import re

import costco
import pendulum
import requests
from addict import Dict as BaseDict
from bs4 import BeautifulSoup

VERBOSE = False


class Dict(BaseDict):
    """Addict is too lenient, this catches small bugs.

    This does sacrifice the ability to set objects and have Addict create necessary parents. But we're only using addict
    for reading json.
    """

    def __missing__(self, key):
        raise KeyError(key)


class LondonDrug:
    @staticmethod
    def get_session_id():
        """Some stupid asp service session crap. Need to emulate selenium or mechanize

        This give session id that is used for actual request.
        """

        # We need to click the "covid19" vaccination link
        # As opposed to some other vaccination, which they doubtfully used this site for
        landing_page = requests.get(
            "https://www.hq3.ca/057/Public/Appointments/Default.aspx"
        )
        landing_page.raise_for_status()
        soup = BeautifulSoup(landing_page.text, "html.parser")

        # Consider using mechanize if this gets any more complicated
        # It's basically a form submit but via a js function, instead of plain html form submission
        form_data = {
            i.attrs["name"]: i.attrs["value"]
            for i in soup.select('input[type="hidden"]')
        }
        # The callback on link is javascript function with "target" embedded
        cta_link = next(
            i for i in soup.select(".servicecategory a") if i.string == "COVID-19"
        )
        form_data["__EVENTTARGET"] = re.search(
            r"__doPostBack\('([^']+)", cta_link.attrs["href"]
        ).group(1)

        # This time we POST and server will give us App session id in response
        landing_page = requests.post(
            "https://www.hq3.ca/057/Public/Appointments/Default.aspx", data=form_data
        )
        soup = BeautifulSoup(landing_page.text, "html.parser")

        session_id = re.search(
            "App=([^&]+)", soup.select_one("#aspnetForm").attrs["action"]
        ).group(1)

        return session_id

    @staticmethod
    def run():
        response = requests.get(
            "https://www.hq3.ca/057/Public/Appointments/NewAppointment/Calendar2.aspx?"
            f"App={LondonDrug.get_session_id()}"
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        times = [
            pendulum.from_format(i.attrs["timeutc"], "MM/DD/YYYY HH:mm A", tz="UTC")
            for i in soup.select(".timeslots a")
        ]

        print("LondonDrug South common mebbe")
        if not times:
            print("No openings at LondonDrug")

        for i in times:
            print(i.in_tz("America/Edmonton").to_time_string())


class Safeway:
    @staticmethod
    def run():
        print("Safeway")
        # This blob is static, from our responses
        data = {
            "eligibilityQuestionResponse": [
                {
                    "id": "q.screening.province",
                    "value": "Alberta",
                    "type": "single-select",
                },
                {
                    "id": "q.screening.alberta.province",
                    "value": "Yes",
                    "type": "single-select",
                },
            ],
            "url": "https://www.pharmacyappointments.ca/screening",
        }
        response = requests.post(
            "https://api.pharmacyappointments.ca/public/eligibility", json=data
        )
        response.raise_for_status()
        token = response.json()["vaccineData"]
        data = {
            "location": {"lat": 53.5461245, "lng": -113.4938229},  # edmonton
            "fromDate": pendulum.today().to_date_string(),
            "vaccineData": token,
            "locationQuery": {"includePools": ["default"]},
            "doseNumber": 1,  # I guess this is first dose
            "url": "https://www.pharmacyappointments.ca/location-select",
        }
        response = requests.post(
            "https://api.pharmacyappointments.ca/public/locations/search", json=data
        )

        locations = Dict(response.json()).locations

        if not locations:
            print("There are no locaitons with upcoming availabilites")
        for location in locations:
            print(location.name)
            store_id = location.extId
            response = requests.post(
                f"https://api.pharmacyappointments.ca/public/locations/{store_id}/availability",
                json={
                    "doseNumber": data["doseNumber"],
                    "startDate": pendulum.today().to_date_string(),
                    "endDate": pendulum.today().add(months=1).to_date_string(),
                    "url": data["url"],
                    "vaccineData": data["vaccineData"],
                },
            )

            response.raise_for_status()
            availability = [
                pendulum.parse(i["date"])
                for i in response.json()["availability"]
                if i["available"]
            ]

            if not availability:
                print("I guess there are no openings in teh next month")

            for day in availability:
                print("{location.name},{day.to_date_string}")
                if VERBOSE:
                    response = requests.post(
                        f"https://api.pharmacyappointments.ca/public/locations/{store_id}/date/{day.to_date_string()}/slots",
                        json={
                            "url": data["url"],
                            "vaccineData": data["vaccineData"],
                        },
                    )
                    response.raise_for_status()
                    slots = [
                        pendulum.today().combine(
                            day, pendulum.parse(i["localStartTime"]).time()
                        )
                        for i in response.json()["slotsWithAvailability"]
                    ]
                    for i in slots:
                        print(i.in_tz("America/Edmonton").to_time_string())


if __name__ == "__main__":
    LondonDrug.run()
    costco.run()
    Safeway.run()
