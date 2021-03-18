from typing import Iterator, cast
from addict import Dict as BaseDict
import pendulum
import requests


class Dict(BaseDict):
    """Addict is too lenient, this catches small bugs.

    This does sacrifice the ability to set objects and have Addict create necessary parents. But we're only using addict
    for reading json.
    """

    def __missing__(self, key):
        raise KeyError(key)


def run() -> None:
    for pharm in get_locations_in_city():
        print(f"Checking Costco {pharm.name}")

        api_id = convert_hippo_id_to_api_id(pharm.hippo_id)

        next_available_date, bookable_days = get_available_days(api_id)
        print(f"Earliest available time is {next_available_date}")
        for i in bookable_days:
            print(i.format("ddd YYYY-MM-DD"))

        if pendulum.parse(next_available_date) > pendulum.today().add(months=1):
            print("No bookings in teh next month...")
            print("Exiting but you could modify script to blindly go ahead.")
        else:
            if len(bookable_days) >= 5:
                bookable_days, ignored = bookable_days[:5], bookable_days[5:]
                print(f"Skipping {len(ignored)} later dates")
            for day in bookable_days:
                times = Coscto.get_times(api_id, day)
                print(f"Available appointments for {day.to_formatted_date_string()}")
                for i in times:
                    print(i.in_tz("America/Edmonton").to_time_string())


def get_locations() -> Iterator[dict]:
    response = requests.get(
        "https://www.costcopharmacy.ca/assets/json/app.clinics.json"
    )
    response.raise_for_status()

    return (
        Dict(
            {
                "name": i["name"],
                "address": i["address"],
                "hippo_id": i["teleHippoId"],
                "city": i["city"],
            }
        )
        for i in response.json()
        if i["isCoVid"]
    )


def get_locations_in_city(city: str = "Edmonton") -> Iterator[dict]:
    return (i for i in get_locations() if i.city == city)


def convert_hippo_id_to_api_id(hippo_id: int) -> int:
    """Use graphql query to get the api id. This is what we actually query with."""

    query = """query ($hippo_id: String!) {
      cRetailerWithSetting(data:{slug:$hippo_id}) {
        data {
          retailer {
            id,name,street,suite,city,state,country,zip,phone,slug,email,timezone,website,startTime,endTime
          }
        },
      }
    }
    """
    variables = {"hippo_id": hippo_id}

    response = requests.post(
        f"https://apipharmacy.telehippo.com/api/c/{hippo_id}/graphql",
        json={"query": query, "variables": variables},
    )
    response.raise_for_status()

    response = Dict(response.json())
    # Oops I didn't actually need everything
    return response.data.cRetailerWithSetting.data.retailer.id


def get_available_days(api_id: int) -> tuple[str, list[pendulum.DateTime]]:
    graphql_query = """query(
        $api_id: Int!,
        $startDate: String!,
        $endDate: String!,
    ) {
        searchBookableWorkTimes (data:{
            retailerId:$api_id,
            startDate:$startDate,
            endDate:$endDate,
            serviceId:988
        }) {
            bookableDays,
            nextAvailableDate,
        }
    }
    """
    variables = {
        "api_id": api_id,
        "startDate": pendulum.today().to_date_string(),
        "endDate": pendulum.today().add(months=1).to_date_string(),
    }
    response = requests.post(
        f"https://apipharmacy.telehippo.com/api/c/{api_id}/graphql",
        json={"query": graphql_query, "variables": variables},
    )
    response.raise_for_status()
    data = Dict(response.json()["data"]["searchBookableWorkTimes"])
    return data.nextAvailableDate, [
        cast(pendulum.DateTime, pendulum.parse(i)) for i in data.bookableDays
    ]


def get_times(api_id, day):
    graphql_query = """query(
        $api_id: Int!,
        $day_of_week: Int!,
        $startDate: String!,
        $endDate: String!,
    ) {
        searchBookableWorkTimes (data:{
            retailerId:$api_id,
            startDate:$startDate,
            endDate:$endDate,
            day:$day_of_week,
            serviceId:988
        }) {
            workTimes   {
                startTimes,
                startDate,
                endTimes,
                endDate,
            },
            events {
                id,
                startTime,
                endTime,
            },
        }
    }
    """
    variables = {
        "api_id": api_id,
        "day_of_week": day.day_of_week,
        "startDate": day.replace(hour=6).to_datetime_string(),
        "endDate": day.add(days=1)
        .replace(hour=5, minute=59, second=59)
        .to_datetime_string(),
    }
    response = requests.post(
        f"https://apipharmacy.telehippo.com/api/c/{api_id}/graphql",
        json={"query": graphql_query, "variables": variables},
    )
    response.raise_for_status()

    data = Dict(response.json()["data"]["searchBookableWorkTimes"])
    store_hours = next(i for i in data.workTimes)
    stupid_format = "ddd MMM DD YYYY HH:mm:ss zZZ (UTC)"
    start_time = (
        pendulum.today()
        .combine(day, pendulum.parse(store_hours.startTimes).time())
        .set(tz="UTC")
    )
    end_time = (
        pendulum.today()
        .combine(day, pendulum.parse(store_hours.endTimes).time())
        .set(tz="UTC")
    )
    if end_time < start_time:
        # Time was meant for next day
        end_time = end_time.add(days=1)

    slots = set(pendulum.period(start_time, end_time).range("minutes", 5))

    booked_times = {
        pendulum.from_format(i.startTime, stupid_format).set(tz="UTC")
        for i in data.events
    }
    return sorted(slots - booked_times)
