from utils.nr_fare_calculator import NRFareManager
from utils.tfl_fare_calculator import *
import re

class RouteParser:
    # All class methods. DO NOT INSTANTIATE!

    @classmethod
    def route_finder(cls, origin: str, destination: str) -> [[(str, str)]]:
        # returns the list of stations, only points of interchange, as a list of tuples
        url = 'https://api.tfl.gov.uk/'
        path = f'Journey/JourneyResults/{origin}/to/{destination}?time=0900&modes=tube,dlr,overground,elizabeth-line,national-rail'

        request_url = url + path

        resp = requests.get(request_url)
        data = resp.json()

        station_tuples = []
        # Iterate over journeys in the response
        for journey in data.get("journeys", []):
            journey_tuples = []
            # Iterate over each leg in the journey
            for leg in journey.get("legs", []):
                # Get the departure and arrival stop points
                departure = leg.get("departurePoint", {})
                arrival = leg.get("arrivalPoint", {})

                # Here we use the "naptanId" as the tfl_code and "commonName" as the station name.
                dep_station = departure.get("naptanId", "")
                arr_station = arrival.get("naptanId", "")

                if not (dep_station == "" or arr_station == ""):
                    # Append the tuple (boarding station, alighting station)
                    journey_tuples.append((dep_station, arr_station))

            if (not journey_tuples in station_tuples) and (not journey_tuples == []):
                station_tuples.append(journey_tuples)

        return cls.combine_lu_legs(station_tuples)

    # where appropriate, combine the journeys of the same type
    # taking advantage that all NR fares start with 910, and non-NR fares start with 940
    @classmethod
    def combine_lu_legs(cls, journeys):
        combined_journeys = []
        for journey in journeys:
            # Discard the journey if any station code does not start with 910 or 940
            if any(not (station.startswith('910') or station.startswith('940'))
                   for leg in journey for station in leg):
                continue

            new_journey = []
            current_non_nr_start = None
            current_non_nr_end = None

            for leg in journey:
                origin, destination = leg
                # Check if the leg is a non-national rail leg (both codes start with 940)
                if origin.startswith('940') and destination.startswith('940'):
                    if current_non_nr_start is None:
                        current_non_nr_start = origin
                    current_non_nr_end = destination
                else:
                    # Flush any accumulated non-national rail segment before processing this leg
                    if current_non_nr_start is not None:
                        new_journey.append((current_non_nr_start, current_non_nr_end))
                        current_non_nr_start = None
                        current_non_nr_end = None
                    new_journey.append(leg)

            # Flush any remaining non-national rail segment at the end of the journey
            if current_non_nr_start is not None:
                new_journey.append((current_non_nr_start, current_non_nr_end))

            combined_journeys.append(new_journey)
        return combined_journeys

    @classmethod
    def journeyTfLFares(cls, journey, time, weekday, railcard) -> {(str, str): float}:
        """
        Calculates TfL fares for any valid partition by calling TfLFareManager.find_fares.
        Outputs a dictionary with keys as tuples (origin, destination) and values as the lowest non-alternative fare.
        """
        # Determine if the time is during peak hours
        time = int(time)
        peak = (630 <= time <= 930 or 1600 <= time <= 1900) and weekday

        fares_dict = {}
        fares_dict[(journey[0][0], journey[-1][1])] = TfLFareManager.find_fares(journey[0][0], journey[-1][1], railcard)

        # Generate all possible origin-destination pairs
        for i in range(len(journey)):
            origin = journey[i][0]
            for j in range(i, len(journey)):
                destination = journey[j][1]
                # Retrieve all fares for this origin-destination pair
                fares = TfLFareManager.find_fares(origin, destination, railcard)
                # Filter out alternative fares and those not matching peak status
                valid_fares = [
                    fare for fare in fares
                    if not fare.is_alternative and fare.is_peak == peak
                ]
                # Find the minimum cost fare
                if valid_fares:
                    min_fare = min(valid_fares, key=lambda f: f.cost)
                    fares_dict[(origin, destination)] = min_fare.cost
                else:
                    fares_dict[(origin, destination)] = float('inf')

        return fares_dict

    @classmethod
    def getTfLDict(cls, origin, destination, time, weekday, railcard):
        routes = RouteParser.route_finder(origin, destination)
        prices = []
        for route in routes:
            prices.append(RouteParser.journeyTfLFares(route, time, weekday, railcard))
        return prices

    @classmethod
    def tfl_code_to_name(cls, tfl_code) -> str:
        url = 'https://api.tfl.gov.uk/'
        path = f'stoppoint/{tfl_code}'
        request_url = url + path

        resp = requests.get(request_url)
        data = resp.json()

        common_name = data['commonName']
        # Remove the station type suffix (e.g., Underground Station, DLR Station, Rail Station)
        name = re.sub(r'\s+(Underground|DLR|Rail)\s+Station$', '', common_name)
        name = re.sub(r' ', '%20', name)
        if name == "London%20Gatwick%20Airport":
            name = "Gatwick%20Airport"
        elif name == "Victoria":
            name = "London%20Victoria"

        return name

    @classmethod
    def journeyNRFares(cls, journey, time, weekday, railcard) -> {(str, str): float}:
        """
        Calculates National Rail fares for valid partitions of the journey, excluding pairs entirely within non-NR stations.
        """
        fares_dict = {}

        # Generate all possible origin-destination pairs
        for i in range(len(journey)):
            origin_tfl = journey[i][0]
            for j in range(i, len(journey)):
                dest_tfl = journey[j][1]

                # Exclude pairs where both stations are non-National Rail (start with 940)
                if origin_tfl.startswith('940') and dest_tfl.startswith('940'):
                    continue

                # Convert TfL codes to NR names
                origin_nr = cls.tfl_code_to_name(origin_tfl)
                dest_nr = cls.tfl_code_to_name(dest_tfl)

                # Calculate NR fare
                fare = NRFareManager.fare_calculator(
                    origin_nr,
                    dest_nr,
                    time="1600",
                    date='2025-03-04',
                    railcard=True
                )

                # Assuming fare is a Fare object with a 'cost' attribute; adjust based on actual implementation
                fares_dict[(origin_tfl, dest_tfl)] = fare.cost

        return fares_dict


    @classmethod
    def getNRDict(cls, origin, destination, time, weekday, railcard):
        routes = RouteParser.route_finder(origin, destination)
        prices = []
        for route in routes:
            prices.append(RouteParser.journeyNRFares(route, time, weekday, railcard))
        return prices

    @classmethod



if __name__ == "__main__":
    print(RouteParser.route_finder('940GZZLUBND', '910GGTWK'))
    print(RouteParser.getTfLDict('940GZZLUBND', '910GGTWK', "1600", True, True))
    print(RouteParser.getNRDict('940GZZLUBND', '910GGTWK', "1600", True, True))