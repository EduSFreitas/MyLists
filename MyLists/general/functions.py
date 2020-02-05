import os
import json
import secrets
import requests
import platform
import urllib.request

from PIL import Image
from pathlib import Path
from flask import url_for
from MyLists import db, app
from sqlalchemy import func
from datetime import datetime
from MyLists.API_data import ApiData
from MyLists.models import ListType, Status, User, AnimeList, Anime, AnimeEpisodesPerSeason, SeriesEpisodesPerSeason, \
    SeriesList, Series, MoviesList, Movies, Badges, SeriesActors, MoviesActors, MoviesCollections, AnimeActors, Ranks


def compute_media_time_spent(list_type):
    users = User.query.all()

    for user in users:
        if list_type == ListType.ANIME:
            element_data = db.session.query(AnimeList, Anime, func.group_concat(AnimeEpisodesPerSeason.episodes))\
                .join(Anime, Anime.id == AnimeList.anime_id)\
                .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == AnimeList.anime_id)\
                .filter(AnimeList.user_id == user.id).group_by(AnimeList.anime_id)
        elif list_type == ListType.SERIES:
            element_data = db.session.query(SeriesList, Series, func.group_concat(SeriesEpisodesPerSeason.episodes))\
                .join(Series, Series.id == SeriesList.series_id)\
                .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id == SeriesList.series_id)\
                .filter(SeriesList.user_id == user.id).group_by(SeriesList.series_id)
        elif list_type == ListType.MOVIES:
            element_data = db.session.query(MoviesList, Movies).join(Movies, Movies.id == MoviesList.movies_id)\
                .filter(MoviesList.user_id == user.id).group_by(MoviesList.movies_id)

        if list_type != ListType.MOVIES:
            total_time = 0
            for element in element_data:
                if element[0].status == Status.COMPLETED:
                    try:
                        total_time += element[1].episode_duration * element[1].total_episodes
                    except:
                        pass
                elif element[0].status != Status.PLAN_TO_WATCH or element[0].status != Status.RANDOM:
                    try:
                        episodes = element[2].split(",")
                        episodes = [int(x) for x in episodes]
                        for i in range(1, element[0].current_season):
                            total_time += element[1].episode_duration * episodes[i-1]
                        total_time += element[0].last_episode_watched * element[1].episode_duration
                    except:
                        pass
        elif list_type == ListType.MOVIES:
            total_time = 0
            for element in element_data:
                if element[0].status != Status.PLAN_TO_WATCH:
                    try:
                        total_time += element[1].runtime
                    except:
                        pass

        if list_type == ListType.ANIME:
            user.time_spent_anime = total_time
        elif list_type == ListType.SERIES:
            user.time_spent_series = total_time
        elif list_type == ListType.MOVIES:
            user.time_spent_movies = total_time

        db.session.commit()


def get_trending_data(trends_data, list_type):
    trending_list = []
    tmdb_posters_path = "http://image.tmdb.org/t/p/w300"

    i = 0
    if list_type == ListType.SERIES:
        trends_data = trends_data.get("results")
        if trends_data is None:
            return None

        for data in trends_data:
            series = {"title": data.get("name", "Unknown") or "Unknown"}
            media_cover_path = data.get("poster_path") or None
            if media_cover_path:
                series["poster_path"] = tmdb_posters_path + media_cover_path
            else:
                series["poster_path"] = url_for('static', filename='covers/series_covers/default.jpg')
            series["first_air_date"] = data.get("first_air_date", "Unknown") or "Unknown"
            if series["first_air_date"] != "Unknown":
                series["first_air_date"] = datetime.strptime(series["first_air_date"], '%Y-%m-%d').strftime("%d %b %Y")
            series["overview"] = data.get("overview", "There is no overview for this series.") \
                                 or "There is no overview for this series."
            series["tmdb_link"] = "https://www.themoviedb.org/tv/{}".format(data.get("id"))
            trending_list.append(series)
            i += 1
            if i > 11:
                break

        return trending_list
    elif list_type == ListType.ANIME:
        trends_data = trends_data.get("top")
        if trends_data is None:
            return None

        for data in trends_data:
            anime = {"title": data.get("title", "Unknown") or "Unknown"}
            media_cover_path = data.get("image_url") or None
            if media_cover_path:
                anime["poster_path"] = media_cover_path
            else:
                anime["poster_path"] = url_for('static', filename='covers/anime_covers/default.jpg')
            anime["first_air_date"] = data.get("start_date", 'Unknown') or "Unknown"
            anime["overview"] = "There is no overview from this API. " \
                                "You can check it on MyAnimeList by clicking on the title"
            anime["tmdb_link"] = data.get("url")
            trending_list.append(anime)
            i += 1
            if i > 11:
                break

        return trending_list
    elif list_type == ListType.MOVIES:
        trends_data = trends_data.get("results")
        if trends_data is None:
            return None

        for data in trends_data:
            movies = {"title": data.get("title", "Unknown") or "Unknown"}
            media_cover_path = data.get("poster_path") or None
            if media_cover_path:
                movies["poster_path"] = tmdb_posters_path + media_cover_path
            else:
                movies["poster_path"] = url_for('static', filename='covers/movies_covers/default.jpg')
            movies["release_date"] = data.get("release_date", "Unknown") or "Unknown"
            if movies["release_date"] != "Unknown":
                movies["release_date"] = datetime.strptime(movies["release_date"], '%Y-%m-%d').strftime("%d %b %Y")
            movies["overview"] = data.get("overview", "No overview available for this movie.") or \
                                 'No overview available for this movie.'
            movies["tmdb_link"] = "https://www.themoviedb.org/movie/{}".format(data.get("id"))
            trending_list.append(movies)
            i += 1
            if i > 11:
                break

        return trending_list


def refresh_db_badges():
    list_all_badges = []
    path = Path(app.root_path, 'static/csv_data/badges.csv')
    with open(path) as fp:
        for line in fp:
            list_all_badges.append(line.split(";"))

    badges = Badges.query.order_by(Badges.id).all()
    for i in range(1, len(list_all_badges)):
        try:
            genre_id = str(list_all_badges[i][4])
        except:
            genre_id = None
        badges[i-1].threshold = int(list_all_badges[i][0])
        badges[i-1].image_id = list_all_badges[i][1]
        badges[i-1].title = list_all_badges[i][2]
        badges[i-1].type = list_all_badges[i][3]
        badges[i-1].genres_id = genre_id


def refresh_db_ranks():
    list_all_ranks = []
    path = Path(app.root_path, 'static/csv_data/ranks.csv')
    with open(path) as fp:
        for line in fp:
            list_all_ranks.append(line.split(";"))

    ranks = Ranks.query.order_by(Ranks.id).all()
    for i in range(1, len(list_all_ranks)):
        ranks[i-1].level = int(list_all_ranks[i][0])
        ranks[i-1].image_id = list_all_ranks[i][1]
        ranks[i-1].name = list_all_ranks[i][2]
        ranks[i-1].type = list_all_ranks[i][3]


# -------------------------------------------- Add data Retroactively ------------------------------------------------ #


def add_ranks_to_db():
    list_all_ranks = []
    path = Path(app.root_path, 'static/csv_data/ranks.csv')
    with open(path) as fp:
        for line in fp:
            list_all_ranks.append(line.split(";"))

    for i in range(1, len(list_all_ranks)):
        rank = Ranks(level=int(list_all_ranks[i][0]),
                     image_id=list_all_ranks[i][1],
                     name=list_all_ranks[i][2],
                     type=list_all_ranks[i][3])
        db.session.add(rank)
    db.session.commit()


def add_badges_to_db():
    list_all_badges = []
    path = Path(app.root_path, 'static/csv_data/badges.csv')
    with open(path) as fp:
        for line in fp:
            list_all_badges.append(line.split(";"))

    for i in range(1, len(list_all_badges)):
        try:
            genre_id = str(list_all_badges[i][4])
        except:
            genre_id = None
        badge = Badges(threshold=int(list_all_badges[i][0]),
                       image_id=list_all_badges[i][1],
                       title=list_all_badges[i][2],
                       type=list_all_badges[i][3],
                       genres_id=genre_id)
        db.session.add(badge)
    db.session.commit()


def add_actors_movies():
    all_movies = Movies.query.all()
    for i in range(0, len(all_movies)):
        tmdb_movies_id = all_movies[i].themoviedb_id
        movies_id = all_movies[i].id
        response = requests.get("https://api.themoviedb.org/3/movie/{0}/credits?api_key={1}"
                                .format(tmdb_movies_id, app.config['THEMOVIEDB_API_KEY']))
        element_actors = json.loads(response.text)

        try:
            actors_names = []
            for j in range(0, len(element_actors["cast"])):
                try:
                    actors_names.append(element_actors["cast"][j]["name"])
                    if j == 3:
                        break
                except:
                    pass
        except:
            pass

        if len(actors_names) == 0:
            actors = MoviesActors(movies_id=movies_id,
                                  name="Unknown")
            db.session.add(actors)
        else:
            for k in range(0, len(actors_names)):
                actors = MoviesActors(movies_id=movies_id,
                                      name=actors_names[k])
                db.session.add(actors)

        db.session.commit()


def add_collections_movies():
    local_covers_path = Path(app.root_path, "static\\covers\\movies_collection_covers\\")
    all_movies = Movies.query.filter_by(themoviedb_id=9799).all()
    for movie in all_movies:
        tmdb_movies_id = movie.themoviedb_id
        try:
            response = requests.get("https://api.themoviedb.org/3/movie/{0}?api_key={1}"
                                    .format(tmdb_movies_id, app.config['THEMOVIEDB_API_KEY']))

            data = json.loads(response.text)

            collection_id = data["belongs_to_collection"]["id"]
            collection_poster = data["belongs_to_collection"]["poster_path"]

            response_collection = requests.get("https://api.themoviedb.org/3/collection/{0}?api_key={1}"
                                               .format(collection_id, app.config['THEMOVIEDB_API_KEY']))

            data_collection = json.loads(response_collection.text)

            collection_name = data_collection["name"]
            collection_overview = data_collection["overview"]

            remove = 0
            utc_now = datetime.utcnow()
            for part in data_collection["parts"]:
                part_date = part['release_date']
                try:
                    part_date_datetime = datetime.strptime(part_date, '%Y-%m-%d')
                    difference = (utc_now-part_date_datetime).total_seconds()
                    if float(difference) < 0:
                        remove += 1
                except:
                    pass

            collection_parts = len(data_collection["parts"]) - remove

            collection_poster_id = "{}.jpg".format(secrets.token_hex(8))

            urllib.request.urlretrieve("http://image.tmdb.org/t/p/w300{}".format(collection_poster),
                                       "{}{}".format(local_covers_path, collection_poster_id))

            img = Image.open("{}{}".format(local_covers_path, collection_poster_id))
            img = img.resize((300, 450), Image.ANTIALIAS)
            img.save("{0}{1}".format(local_covers_path, collection_poster_id), quality=90)

            movie.collection_id = collection_id

            # Test if collection already in MoviesCollection
            if MoviesCollections.query.filter_by(collection_id=collection_id).first() is not None:
                db.session.commit()
                continue

            add_collection = MoviesCollections(collection_id=collection_id,
                                               parts=collection_parts,
                                               name=collection_name,
                                               poster=collection_poster_id,
                                               overview=collection_overview)

            db.session.add(add_collection)
            db.session.commit()
        except:
            continue


def add_actors_series():
    all_series = Series.query.all()
    for i in range(0, len(all_series)):
        tmdb_series_id = all_series[i].themoviedb_id
        series_id = all_series[i].id
        response = requests.get("https://api.themoviedb.org/3/tv/{0}/credits?api_key={1}"
                                .format(tmdb_series_id, app.config['THEMOVIEDB_API_KEY']))
        element_actors = json.loads(response.text)

        try:
            actors_names = []
            for j in range(0, len(element_actors["cast"])):
                try:
                    actors_names.append(element_actors["cast"][j]["name"])
                    if j == 3:
                        break
                except:
                    pass
        except:
            pass

        if len(actors_names) == 0:
            actors = SeriesActors(series_id=series_id,
                                  name="Unknown")
            db.session.add(actors)
        else:
            for k in range(0, len(actors_names)):
                actors = SeriesActors(series_id=series_id,
                                      name=actors_names[k])
                db.session.add(actors)

        db.session.commit()


def add_actors_anime():
    all_anime = Anime.query.all()
    for i in range(0, len(all_anime)):
        tmdb_anime_id = all_anime[i].themoviedb_id
        anime_id = all_anime[i].id
        response = requests.get("https://api.themoviedb.org/3/tv/{0}/credits?api_key={1}"
                                .format(tmdb_anime_id, app.config['THEMOVIEDB_API_KEY']))
        element_actors = json.loads(response.text)

        try:
            actors_names = []
            for j in range(0, len(element_actors["cast"])):
                try:
                    actors_names.append(element_actors["cast"][j]["name"])
                    if j == 3:
                        break
                except:
                    pass
        except:
            pass

        if len(actors_names) == 0:
            actors = AnimeActors(anime_id=anime_id,
                                 name="Unknown")
            db.session.add(actors)
        else:
            for k in range(0, len(actors_names)):
                actors = AnimeActors(anime_id=anime_id,
                                     name=actors_names[k])
                db.session.add(actors)

        db.session.commit()


# ------------------------------------------- TMDb API Update Scheduler ---------------------------------------------- #


def refresh_element_data(api_id, list_type):
    details_data = ApiData().get_details_and_credits_data(api_id, list_type)

    if list_type == ListType.SERIES:
        element = Series.query.filter_by(themoviedb_id=api_id).first()
    elif list_type == ListType.ANIME:
        element = Anime.query.filter_by(themoviedb_id=api_id).first()
    elif list_type == ListType.MOVIES:
        element = Movies.query.filter_by(themoviedb_id=api_id).first()

    if details_data is None or element is None:
        app.logger.info('[SYSTEM] Could not refresh the element with the TMDb ID {}'.format(api_id))
    else:
        if list_type != ListType.MOVIES:
            name = details_data.get("name", "Unknown") or "Unkwown"
            original_name = details_data.get("original_name", "Unknown") or "Unkwown"
            first_air_date = details_data.get("first_air_date", "Unknown") or "Unkwown"
            last_air_date = details_data.get("last_air_date", "Unknown") or "Unkwown"
            homepage = details_data.get("homepage", "Unknown") or "Unkwown"
            in_production = details_data.get("in_production", False) or False
            total_seasons = details_data.get("number_of_seasons", 0) or 0
            total_episodes = details_data.get("number_of_episodes", 0) or 0
            status = details_data.get("status", "Unknown") or "Unknown"
            vote_average = details_data.get("vote_average", 0) or 0
            vote_count = details_data.get("vote_count", 0) or 0
            synopsis = details_data.get("overview", "No overview available.") or "No overview available."
            popularity = details_data.get("popularity", 0) or 0
            poster_path = details_data.get("poster_path", "") or ""

            # Refresh Created by: list
            created_by = details_data.get("created_by") or None
            if created_by:
                creators = []
                for creator in created_by:
                    tmp_created = creator.get("name") or None
                    if tmp_created:
                        creators.append(tmp_created)
                created_by = ", ".join(x for x in creators)
            else:
                created_by = 'Unknown'

            # Refresh Episode duration: list
            episode_duration = details_data.get("episode_run_time") or None
            if episode_duration:
                episode_duration = episode_duration[0]
            else:
                if list_type == ListType.ANIME:
                    episode_duration = 24
                elif list_type == ListType.SERIES:
                    episode_duration = 45

            # Refresh Origin country: list
            origin_country = details_data.get("origin_country", "Unknown") or "Unknown"
            if "Unknown" not in origin_country:
                origin_country = origin_country[0]

            # Refresh if a special season exist, we do not want to take it into account
            seasons_data = []
            if len(details_data["seasons"]) == 0:
                return None

            if details_data["seasons"][0]["season_number"] == 0:
                for i in range(len(details_data["seasons"])):
                    try:
                        seasons_data.append(details_data["seasons"][i + 1])
                    except:
                        pass
            else:
                for i in range(len(details_data["seasons"])):
                    try:
                        seasons_data.append(details_data["seasons"][i])
                    except:
                        pass

            # Refresh the cover
            if list_type == ListType.SERIES:
                if platform.system() == "Windows":
                    local_covers_path = os.path.join(app.root_path, "static\\covers\\series_covers\\")
                else:  # Linux & macOS
                    local_covers_path = os.path.join(app.root_path, "static/covers/series_covers/")
            elif list_type == ListType.ANIME:
                if platform.system() == "Windows":
                    local_covers_path = os.path.join(app.root_path, "static\\covers\\anime_covers\\")
                else:  # Linux & macOS
                    local_covers_path = os.path.join(app.root_path, "static/covers/anime_covers/")

            # Refresh the cover
            try:
                if poster_path != "":
                    urllib.request.urlretrieve("http://image.tmdb.org/t/p/w300{0}".format(poster_path),
                                               "{}{}".format(local_covers_path, element.image_cover))

                    img = Image.open(local_covers_path + element.image_cover)
                    img = img.resize((300, 450), Image.ANTIALIAS)
                    img.save(local_covers_path + element.image_cover, quality=90)
            except:
                app.logger.info("Error while refreshing the cover of ID {}".format(element.id))
                pass

            # Refresh the data for Anime/Series
            element.name = name
            element.original_name = original_name
            element.first_air_date = first_air_date
            element.last_air_date = last_air_date
            element.homepage = homepage
            element.in_production = in_production
            element.created_by = created_by
            element.episode_duration = episode_duration
            element.total_seasons = total_seasons
            element.total_episodes = total_episodes
            element.origin_country = origin_country
            element.status = status
            element.vote_average = vote_average
            element.vote_count = vote_count
            element.synopsis = synopsis
            element.popularity = popularity

            # Update the number of seasons and episodes
            for season_data in seasons_data:
                if list_type == ListType.SERIES:
                    season = SeriesEpisodesPerSeason.query.filter_by(series_id=element.id,
                                                                     season=season_data["season_number"]).first()
                    if season is None:
                        season = SeriesEpisodesPerSeason(series_id=element.id,
                                                         season=season_data["season_number"],
                                                         episodes=season_data["episode_count"])
                        db.session.add(season)
                    else:
                        season.episodes = season_data["episode_count"]
                elif list_type == ListType.ANIME:
                    season = AnimeEpisodesPerSeason.query.filter_by(anime_id=element.id,
                                                                    season=season_data["season_number"]).first()
                    if season is None:
                        season = AnimeEpisodesPerSeason(anime_id=element.id,
                                                        season=season_data["season_number"],
                                                        episodes=season_data["episode_count"])
                        db.session.add(season)
                    else:
                        season.episodes = season_data["episode_count"]

            # TODO: Refresh networks, genres and actors

            element.last_update = datetime.utcnow()
            db.session.commit()
            app.logger.info("[SYSTEM] Refreshed the series/anime with the ID {}".format(element.id))
        elif list_type == ListType.MOVIES:
            release_date = details_data.get("release_date", "Unknown") or "Unknown"
            homepage = details_data.get("homepage", "Unknown") or "Unknown"
            released = details_data.get("status", False) or False
            vote_average = details_data.get("vote_average", 0) or 0
            vote_count = details_data.get("vote_count", 0) or 0
            synopsis = details_data.get("overview", "No overview available.") or "No overview available."
            popularity = details_data.get("popularity", 0) or 0
            budget = details_data.get("budget", 0) or 0
            revenue = details_data.get("revenue", 0) or 0
            tagline = details_data.get("tagline", "-") or '-'
            runtime = details_data.get("runtime", 90) or 90
            original_language = details_data.get("original_language", "Unknown") or "Unknown"
            collection_id = details_data.get("belongs_to_collection") or None
            poster_path = details_data.get("poster_path") or None

            # Refresh the cover
            if platform.system() == "Windows":
                local_covers_path = os.path.join(app.root_path, "static\\covers\\movies_covers\\")
            else:  # Linux & macOS
                local_covers_path = os.path.join(app.root_path, "static/covers/movies_covers/")

            # Refresh the cover
            try:
                if poster_path != "":
                    urllib.request.urlretrieve("http://image.tmdb.org/t/p/w300{0}".format(poster_path),
                                               "{}{}".format(local_covers_path, element.image_cover))

                    img = Image.open(local_covers_path + element.image_cover)
                    img = img.resize((300, 450), Image.ANTIALIAS)
                    img.save(local_covers_path + element.image_cover, quality=90)
            except:
                app.logger.info("Error while refreshing the movie cover of ID {}".format(element.id))
                pass

            # Refresh the movies data
            element.release_date = release_date
            element.released = released
            element.homepage = homepage
            element.runtime = runtime
            element.original_language = original_language
            element.vote_average = vote_average
            element.vote_count = vote_count
            element.synopsis = synopsis
            element.popularity = popularity
            element.budget = budget
            element.revenue = revenue
            element.tagline = tagline
            element.collection_id = collection_id

            # TODO: Refresh genres and actors

            db.session.commit()
            app.logger.info("[SYSTEM] Refreshed the movie with the ID {}".format(element.id))


def automatic_media_refresh():
    app.logger.info('[SYSTEM] Starting automatic refresh')

    # Recover all the data
    all_movies = Movies.query.all()
    all_series = Series.query.all()
    all_anime = Anime.query.all()

    # Create a list containing all the Movies TMDb ID
    all_movies_tmdb_id_list = []
    for movie in all_movies:
        all_movies_tmdb_id_list.append(movie.themoviedb_id)

    # Create a list containing all the Series TMDb ID
    all_series_tmdb_id_list = []
    for series in all_series:
        all_series_tmdb_id_list.append(series.themoviedb_id)

    # Create a list containing all the Anime TMDb ID
    all_anime_tmdb_id_list = []
    for anime in all_anime:
        all_anime_tmdb_id_list.append(anime.themoviedb_id)

    # Recover from API all the changed Movies ID
    try:
        response = requests.get("https://api.themoviedb.org/3/movie/changes?api_key={0}"
                                .format(app.config['THEMOVIEDB_API_KEY']))
    except Exception as e:
        app.logger.error('[SYSTEM] Error requesting themoviedb API: {}'.format(e))
        return
    if response.status_code == 401:
        app.logger.error('[SYSTEM] Error requesting themoviedb API: invalid API key')
        return

    try:
        all_id_movies_changes = json.loads(response.text)
    except:
        return

    # Recover from API all the changed series/anime ID
    try:
        response = requests.get("https://api.themoviedb.org/3/tv/changes?api_key={0}"
                                .format(app.config['THEMOVIEDB_API_KEY']))
    except Exception as e:
        app.logger.error('[SYSTEM] Error requesting themoviedb API : {}'.format(e))
        return
    if response.status_code == 401:
        app.logger.error('[SYSTEM] Error requesting themoviedb API : invalid API key')
        return

    try:
        all_id_tv_changes = json.loads(response.text)
    except:
        return

    # Funtion to refresh movies
    for element in all_id_movies_changes["results"]:
        if element["id"] in all_movies_tmdb_id_list:
            refresh_element_data(element["id"], ListType.MOVIES)

    # Funtion to refresh series
    for element in all_id_tv_changes["results"]:
        if element["id"] in all_series_tmdb_id_list:
            refresh_element_data(element["id"], ListType.SERIES)

    # Funtion to refresh anime
    for element in all_id_tv_changes["results"]:
        if element["id"] in all_anime_tmdb_id_list:
            refresh_element_data(element["id"], ListType.ANIME)

    app.logger.info('[SYSTEM] Automatic refresh completed')


app.apscheduler.add_job(func=automatic_media_refresh, trigger='cron', hour=3, id="{}".format(secrets.token_hex(8)))