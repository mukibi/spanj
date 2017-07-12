#!/usr/bin/perl

use strict;
use warnings;
use DBI;

require  "./conf.pl";

my $content = "";
our ($db,$db_user,$db_pwd);
my %session;
my $update_session = 0;
my $con;

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/analysis.cgi">Run Analysis</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/viewdataset.cgi">View Dataset</a>
	<hr> 
};

#load up the session data 
if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;
	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}
}

$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError' => 1, 'AutoCommit' =>  0});

#determine dataset

#what student rolls are there?
my %classes;
my $current_yr = (localtime)[5] + 1900;

my $prep_stmt_3_0 = $con->prepare("SELECT table_name,class,start_year,grad_year FROM student_rolls");

if ($prep_stmt_3_0) {
	my $rc = $prep_stmt_3_0->execute();
	if ($rc) {
		while (my @rslts = $prep_stmt_3_0->fetchrow_array()) {
			my ($stud_roll,$class,$start_year,$grad_year) = @rslts;
			$classes{$stud_roll} = {"class" => $class, "start_year" => $start_year, "grad_year" => $grad_year};
		}
	}
	else {
		print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt_3_0->errstr, $/;
	}
}
else {
	print STDERR "Could not prepare SELECT FROM student_rolls statement: ", $prep_stmt_3_0->errstr, $/;
}

#is there any class lim?
if (exists $session{"classes"}) {
	my @classes = split/,/, lc($session{"classes"});	
	my %wanted_classes = ();
	@wanted_classes{@classes} = @classes;	
	for my $roll (keys %classes) {
		my ($class, $start, $grad) = ( ${$classes{$roll}}{"class"}, ${$classes{$roll}}{"start_year"}, ${$classes{$roll}}{"grad_year"} );
		my $match = 0;
		my $yr;	
		H: for (my $i = $start; $i <= $grad; $i++) { 

			$yr = ($i - $start) + 1;
			$class =~ s/\d+/$yr/;
			my $reformd_class = lc($class . "(" . $grad . ")");	
			if (exists $wanted_classes{$reformd_class}) {	
				$match++;	
				${$classes{$roll}}{"year"} = $i;
				last H;
			}
		}
		unless ($match) {	
			delete $classes{$roll};	
		}
	}
}
#only use current students
else {
	for my $class (keys %classes) {
		unless ($current_yr <= ${$classes{$class}}{"grad_year"} and $current_yr >= ${$classes{$class}}{"start_year"}) {
			delete $classes{$class};					
		}
		else {
			${$classes{$class}}{"year"} = $current_yr;
		}
	}
}

if (keys %classes) {
	#check other conditions
	my @where_clause = ();
	my @bind_vals = ();

	#clubs_societies
	if (exists $session{"clubs_societies"}) {
		my @clubs = split/,/, lc($session{"clubs_societies"});
		my @clubs_like = ();
		for my $club (@clubs) {	
			push @clubs_like, "clubs_societies LIKE ?";
			push @bind_vals, "%$club%";
		}
		my $clubs_lim = "(" . join(" OR ", @clubs_like) . ")";
		push @where_clause, $clubs_lim;
	}

	#responsilities
	if (exists $session{"responsibilities"}) {
		my @respons = split/,/, lc($session{"responsibilities"});
		my @respons_like = ();
		for my $respon (@respons) {
			push @respons_like, "responsibilities LIKE ?";
			push @bind_vals, "%$respon%";
		}
		my $respons_lim = "(" . join(" OR ", @respons_like) . ")";
		push @where_clause, $respons_lim;
	}

	#sports_games
	if (exists $session{"sports_games"}) {
		my @games = split/,/, lc($session{"sports_games"});
		my @games_like = ();
		for my $game (@games) {
			push @games_like, "sports_games LIKE ?";
			push @bind_vals, "%$game%";
		}
		my $games_lim = "(" . join(" OR ", @games_like) . ")";
		push @where_clause, $games_lim;
	}

	#dorms
	if (exists $session{"dorms"}) {
		my @dorms = split/,/, lc($session{"dorms"});
		my @dorms_like = ();
		for my $dorm (@dorms) {
			push @dorms_like, "house_dorm LIKE ?";
			push @bind_vals, "%$dorm%";
		}
		my $dorms_lim = "(" . join(" OR ", @dorms_like) . ")";
		push @where_clause, $dorms_lim;
	}

	#marks_at_adm
	if (exists $session{"marks_at_adm"}) {
		my $lim = $session{"marks_at_adm"};
		my $marks_at_adm_lim = "(marks_at_adm $lim)";
		push @where_clause, $marks_at_adm_lim;
	}
	
	my $where = "";
	if (@where_clause) {
		$where = " WHERE " . join(" AND ", @where_clause);
	}

	my %matching_adms = ();
	my $prep_stmt_3_2;

	for my $class (keys %classes) {
		my $class_name = ${$classes{$class}}{"class"};
		my $class_yr = (${$classes{$class}}{"year"} - ${$classes{$class}}{"start_year"}) + 1;
	
		$class_name =~ s/\d+/$class_yr/;

		$prep_stmt_3_2 = $con->prepare("SELECT adm,s_name,o_names FROM `${class}${where}`");

		if ($prep_stmt_3_2) {	
			my $rc = $prep_stmt_3_2->execute(@bind_vals);
			if ($rc) {
				while (my @rslts = $prep_stmt_3_2->fetchrow_array()) {
					my ($adm, $s_name, $o_names) = @rslts;
					$matching_adms{$adm} = {"name" => "$s_name $o_names", "class" => $class_name};	
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM $class statement: ", $prep_stmt_3_2->errstr, $/;
			}	
		}
		else {
			print STDERR "Could not prepare SELECT FROM $class statement: ", $prep_stmt_3_2->errstr, $/;
		}
	}

	my $dataset_size = scalar(keys %matching_adms);

	if ($dataset_size > 0) {
		$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: Run Analysis</title>
</head>
<body>
$header
<p>
<table border="1">
<thead><th>&nbsp;<th>Adm No.<th>Name<th>Class</thead>
<tbody>
*;
		my $cntr = 0;
		foreach (sort {$a <=> $b} keys %matching_adms) {
			++$cntr;
			$content .= qq!<tr><td>$cntr<td><a href="/cgi-bin/viewresults.cgi?adm=$_">$_</a><td>${$matching_adms{$_}}{"name"}<td>${$matching_adms{$_}}{"class"}!;	
		}
		$content .= "</tbody></table></body></html>";	
	}
	#Fail- No matching students
	else {
		$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: Run Analysis</title>
</head>
<body>
$header
<em>None of the students match the conditions specified.</em>
</body>
</html>
*;
	}
}

#Early fail- no such class/es
else {
	my $error_msg = "<em>There are no classes created in the system.</em>";
	if (exists $session{"classes"}) {
		$error_msg = "<em>None of the classes you selected exists in the system.</em>";
	}

	$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>Spanj :: Exam Management Information System :: View Dataset</title>
</head>
<body>
$header
$error_msg
</body>
</html>
*;
}


print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";
print "\r\n";
print $content;
$con->disconnect();

