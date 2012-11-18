import sys
import uuid
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import render, render_to_response, get_object_or_404, redirect
from recipe.models import Recipe, RecipeCategory, Vote, Step, Amount
from recipe.forms import RecipeForm, VoteForm, StepForm, AmountForm, DidRecipeForm
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.views.generic import DetailView, ListView
from django.views.generic.edit import CreateView
from recipe import recommendations
from recipe.tasks import add_view_num, get_or_create_vote, add_like_num
from django.core.urlresolvers import reverse
from food.models import Food, FoodCategory
from django.core import serializers
from actstream import actions, models
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.forms.formsets import formset_factory
from django.conf import settings
from ajaxuploader.views import AjaxFileUploader
from ajaxuploader.backends.easythumbnails import EasyThumbnailUploadBackend

did_image_upload = AjaxFileUploader(backend=EasyThumbnailUploadBackend, DIMENSIONS=(540,000), QUALITY=90, UPLOAD_DIR='Recipe_Images/Did_Images')

cover_image_upload = AjaxFileUploader(backend=EasyThumbnailUploadBackend, DIMENSIONS=(540,000), QUALITY=90, UPLOAD_DIR='Recipe_Images/Cover_Images')

step_image_upload = AjaxFileUploader(backend=EasyThumbnailUploadBackend, DIMENSIONS=(160,000), QUALITY=75, UPLOAD_DIR='Recipe_Images/Step_Image')

def nav(request):
	return render(request, 'nav.html')

def index(request):
	if request.is_ajax():
		data = ''
		q = request.POST['q']
		queries = {}
		queries['recipe'] = Recipe.objects.filter(name__contains= q)[:3]
		queries['food'] = Food.objects.filter(name__contains=q)[:3]
		print>>sys.stderr, queries
		return render_to_response('autocomplete.html',{'recipe_list':queries['recipe'], 'food_list':queries['food']})
	else:
		return render(request, 'recipe/index.html')

class RecipeDetailView(DetailView):
	queryset = Recipe.objects.all()

	def get_object(self):
		object = super(RecipeDetailView, self).get_object()

		add_view_num.delay(object)

		return object

	def get_context_data(self, **kwargs):
		context = super(RecipeDetailView, self).get_context_data(**kwargs)
		
		context['recommends'] = recommendations.recommendRecipeForRecipe(context['object'].id, 10)

		if self.request.user.is_authenticated():
			try:
				vote = Vote.objects.get(recipe = context['object'], user=self.request.user)
			except Vote.DoesNotExist:
				context['vote'] = None
			else:
				context['vote'] = vote
		
		context['votelist'] = Vote.objects.filter(recipe = context['object']).order_by('-date')
		return context

class RecipeCategoryListView(ListView):
	context_object_name = "recipe_list"
	paginate_by = 10

	def get_queryset(self):		
		if self.args[1] == 'hot':
			self.recipecategory = get_object_or_404(RecipeCategory, id__iexact=self.args[0])
			return Recipe.objects.filter(category = self.recipecategory)
		elif self.args[1] == 'time':
			self.recipecategory = get_object_or_404(RecipeCategory, id__iexact=self.args[0])
			return Recipe.objects.filter(category = self.recipecategory).order_by("-date")
		elif self.args[1] == 'trend':
			self.recipecategory = get_object_or_404(RecipeCategory, id__iexact=self.args[0])
			return Recipe.objects.filter(category = self.recipecategory).order_by("-trend_num")
		else:
			raise Http404

	def get_context_data(self, **kwargs):
		context = super(RecipeCategoryListView, self).get_context_data(**kwargs)
		context['category'] = self.recipecategory
		return context

class HotRecipeListView(ListView):
	queryset = Recipe.objects.all()
	context_object_name = "hot_recipe_list"
	template_name = "recipe/hot_recipe_list.html"
	paginate_by = 10

@login_required
def rate(request, pk):
	if request.is_ajax():
		user = request.user.id
		form = VoteForm(request.POST)
		if form.is_valid():
			score = form.cleaned_data['score']
			comment = form.cleaned_data['comment']
			get_or_create_vote.delay(pk, user, score, comment)
			return HttpResponse('<div id="ajax-feedback">Success</div>')
		else:
			return HttpResponse('<div id="ajax-feedback">Failed</div>')
	else:
		raise Http404


@login_required
def like(request, pk):
	"""
	Handle ajax request to like a recipe from a user 
	"""
	if request.is_ajax():
		recipe = get_object_or_404(Recipe, pk=pk)
		profile = request.user.get_profile()
		profile.favourite_recipes.add(recipe)
		action.send(request.user, verb='liked', target = recipe)
		add_like_num.delay(recipe, 1)

		return HttpResponse('Liked')
	else:
		raise Http404	


@login_required
def unlike(request, pk):
	"""
	Handle ajax request to unlike a recipe from a user 
	"""
	if request.is_ajax():
		recipe = get_object_or_404(Recipe, pk=pk)
		profile = request.user.get_profile()
		profile.favourite_recipes.remove(recipe)
		action.send(request.user, verb='liked', target = recipe)
		add_like_num.delay(recipe, -1)

		return HttpResponse('Liked')
	else:
		raise Http404	


@login_required
def activity(request):
    """
    Index page for authenticated user's activity stream. 
    """
    return render(request, 'actstream/update.html', {
        'ctype': ContentType.objects.get_for_model(User),
        'actor': request.user, 'action_list': models.user_stream(request.user),
        'following': models.following(request.user),
        'followers': models.followers(request.user),
    })

@login_required
def recipe_create(request):
	"""
	Page for create a new recipe
	"""    
	AmountFormSet = formset_factory(AmountForm, extra = 1)
	StepFormSet = formset_factory(StepForm, extra = 1)
	if request.method == 'POST':
		recipe_form = RecipeForm(request.POST)
		amount_formset = AmountFormSet(request.POST, prefix='amount')
		step_formset = StepFormSet(request.POST, prefix='step')
		if recipe_form.is_valid() and amount_formset.is_valid() and step_formset.is_valid():
			print >> sys.stderr, 'valid!!!!!!!!!!!!!!!!'
			r = recipe_form.save()
			step = 0
			for form in step_formset:
				des = ''
				if 'description' in form.cleaned_data:
					des = form.cleaned_data['description']
				else:
					continue
				s = Step(recipe = r, step_num = step, description = des)
				s.step_image = form.cleaned_data['step_image'];
				s.save()
				step = step + 1

			unactive = get_object_or_404(FoodCategory, pk = 1)
			for form in amount_formset:
				if 'ingredient' in form.cleaned_data:
					f, created = Food.objects.get_or_create(name = form.cleaned_data['ingredient'], defaults={'category': unactive})
					a = Amount(ingredient = f, recipe = r, amount = form.cleaned_data['amount'], must = form.cleaned_data['must'])
					a.save()
				else:
					continue

			return redirect(r)

	else:
		recipe_form = RecipeForm(initial={'author': request.user.id})
		amount_formset = AmountFormSet(prefix='amount')
		step_formset = StepFormSet(prefix='step')

	return render(request, 'recipe/recipe_form.html',{
		'recipe_form': recipe_form,
		'amount_formset': amount_formset,
		'step_formset': step_formset,
		})

@login_required
def recipe_edit(request, pk):
	"""
	Page for edit a recipe
	"""    
	recipe = get_object_or_404(Recipe, pk = pk)
	if request.user != recipe.author:
		raise Http404
	AmountFormSet = formset_factory(AmountForm, extra = 1)
	StepFormSet = formset_factory(StepForm, extra = 1)
	if request.method == 'POST':
		recipe_form = RecipeForm(request.POST, instance = recipe)
		amount_formset = AmountFormSet(request.POST, prefix='amount')
		step_formset = StepFormSet(request.POST, prefix='step')
		if recipe_form.is_valid() and amount_formset.is_valid() and step_formset.is_valid():
			r = recipe_form.save()
			
			# Process step
			step = 0
			for form in step_formset:
				des = ''
				if 'description' in form.cleaned_data:
					des = form.cleaned_data['description']
				else:
					continue
				s, created = Step.objects.get_or_create(recipe = r, step_num= step, defaults={'description': des})
				s.description = des
				s.step_image = form.cleaned_data['step_image'];
				s.save()
				step = step + 1

			# Process amount
			unactive = get_object_or_404(FoodCategory, pk = 1)
			for form in amount_formset:
				if 'ingredient' in form.cleaned_data:
					f, created = Food.objects.get_or_create(name = form.cleaned_data['ingredient'], defaults={'category': unactive})
					a, created = Amount.objects.get_or_create(ingredient = f, recipe = r, defaults={'amount':form.cleaned_data['amount'], 'must':form.cleaned_data['must']})
					a.amount = form.cleaned_data['amount']
					a.must = form.cleaned_data['must']
					a.save()
				else:
					continue

			return redirect(r)


	else:
		""" Give initial data """
		recipe_form = RecipeForm(instance = recipe)

		amount = recipe.amount_set.all()
		initial_amount = []
		for a in amount:
			initial_amount.append({	'ingredient':a.ingredient,
									'amount': a.amount,
									'must': a.must,
									})

		step = recipe.step_set.all()
		initial_step = []
		for s in step:
			initial_step.append({	'description':s.description,
									'step_image':s.step_image.url
									})

		amount_formset = AmountFormSet(initial = initial_amount ,prefix='amount')
		step_formset = StepFormSet(initial = initial_step, prefix='step')

	return render(request, 'recipe/recipe_form.html',{
		'recipe_form': recipe_form,
		'amount_formset': amount_formset,
		'step_formset': step_formset,
		})

@login_required
def recipe_delete(request, pk):
	recipe = get_object_or_404(Recipe, pk = pk)
	name = recipe.name
	if recipe.author == request.user:
		recipe.amount_set.all().delete()
		recipe.step_set.all().delete()
		recipe.delete()
		return render(request, 'recipe/recipe_delete.html', {'recipe': name,})

	else:
		raise Http404

@login_required
def did_recipe_upload(request, pk):
	recipe = get_object_or_404(Recipe, pk = pk)
	if request.method == 'POST':
		form = DidRecipeForm(request.POST, request.FILES)
		if form.is_valid():
			if request.user != form.cleaned_data['user']:
				raise Http404
			form.save()

		return redirect(recipe)
	else:
		form = DidRecipeForm(initial= {'recipe': recipe.id, 'user': request.user.id,})

	return render(request, 'recipe/did_form.html', {
			'form': form,
		})